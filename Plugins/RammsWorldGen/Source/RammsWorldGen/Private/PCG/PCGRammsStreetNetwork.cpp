// Copyright ATDev. All Rights Reserved.
#include "PCG/PCGRammsStreetNetwork.h"

#include "PCGContext.h"
#include "RammsWorldGenModule.h"
#include "PCGModule.h"
#include "PCGPin.h"

#define LOCTEXT_NAMESPACE "RammsPCG"

TArray<FPCGPinProperties> UPCGRammsStreetNetworkSettings::InputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	FPCGPinProperties& In = Pins.Emplace_GetRef(RammsPCG::PinIn, EPCGDataType::Spatial, /*bAllowMultipleConnections=*/false, /*bAllowMultipleData=*/false,
		LOCTEXT("InTooltip", "The generator's bounds. Wire the Input node's In pin here."));
	In.SetRequiredPin();
	return Pins;
}

TArray<FPCGPinProperties> UPCGRammsStreetNetworkSettings::OutputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace(RammsPCG::PinPrimitives, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinProps, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinPieces, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinBlocks, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinSidewalks, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinFeatures, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinRoads, EPCGDataType::Spline);
	return Pins;
}

FPCGElementPtr UPCGRammsStreetNetworkSettings::CreateElement() const
{
	return MakeShared<FPCGRammsStreetNetworkElement>();
}

namespace
{
	struct FSeg
	{
		bool bAlongX = true; // runs along X at y = Lines Y[j], between X[i] and X[i+1]; else along Y at x = X[i] between Y[j] and Y[j+1]
		int32 I = 0, J = 0;
		bool bLive = true;
	};

	struct FBlock
	{
		int32 Id = 0;
		double X0 = 0, X1 = 0, Y0 = 0, Y1 = 0; // centreline rectangle
		bool bPark = false;
		bool bLawn = false; // ground is lawn (parks always; built blocks when LawnLots says so)
	};

	// One side of a block's sidewalk ring. Local frame: origin at Start on the
	// curb line, +X along Dir, +Y = Inward (toward the lots). Yaw rotates world
	// +X onto Dir, and world +Y onto Inward.
	struct FSide
	{
		int32 BlockId = 0;
		int32 Index = 0; // 0 south, 1 east, 2 north, 3 west
		FVector Start = FVector::ZeroVector;
		FVector Dir = FVector::ForwardVector;
		FVector Inward = FVector::RightVector;
		double Length = 0.0;
		double Yaw = 0.0;
		TArray<FVector2D> Keepouts; // [along start, along end] of curb ramps
	};

	FVector2D RandomLineSpacings(const FRandomStream& Rng, double Total, double Min, double Max, double RoadWidth, TArray<double>& Out)
	{
		// Lines from -Total/2 + RW/2 to Total/2 - RW/2, with block sizes drawn from [Min, Max].
		Out.Reset();
		const double Lo = -Total * 0.5 + RoadWidth * 0.5;
		const double Hi = Total * 0.5 - RoadWidth * 0.5;
		Out.Add(Lo);
		double Pos = Lo;
		while (true)
		{
			const double Block = RammsPCG::RandRange(Rng, Min, Max);
			const double Next = Pos + Block + RoadWidth;
			if (Next + (Min + RoadWidth) * 0.6 > Hi)
			{
				break;
			}
			Out.Add(Next);
			Pos = Next;
		}
		if (Out.Last() < Hi - 1.0)
		{
			Out.Add(Hi);
		}
		return FVector2D(Lo, Hi);
	}
}

bool FPCGRammsStreetNetworkElement::ExecuteInternal(FPCGContext* Context) const
{
	const UPCGRammsStreetNetworkSettings* S = Context->GetInputSettings<UPCGRammsStreetNetworkSettings>();
	check(S);
	{
		static int32 ExecCount = 0;
		++ExecCount;
		const int32 NumIn = Context->InputData.GetInputsByPin(RammsPCG::PinIn).Num();
		const int32 NumOverrides = Context->InputData.GetParamsByPin(FName(TEXT("Overrides"))).Num();
		const int32 NumAll = Context->InputData.TaggedData.Num();
		UE_LOG(LogRammsWorldGen, Verbose, TEXT("%s: execution #%d, In=%d Overrides=%d all inputs=%d seed=%d"), *S->GetName(), ExecCount, NumIn, NumOverrides, NumAll, Context->GetSeed());
		for (const FPCGTaggedData& T : Context->InputData.TaggedData)
		{
			UE_LOG(LogRammsWorldGen, Verbose, TEXT("    input pin=%s data=%s tags=%s"), *T.Pin.ToString(), T.Data ? *T.Data->GetClass()->GetName() : TEXT("null"), *FString::Join(T.Tags.Array(), TEXT(",")));
		}
	}

	const int32 Seed = Context->GetSeed();
	FRandomStream Rng(Seed);
	const URammsWorldPalette* Palette = RammsPCG::LoadPalette(S->Palette, Context);

	const FBox Bounds = RammsPCG::InputBounds(Context, RammsPCG::PinIn, FVector(S->SiteSizeX, S->SiteSizeY, 1000.0));
	const FVector Centre = Bounds.GetCenter();
	const double Z0 = Centre.Z;             // sidewalk level
	const double RW = FMath::Max(S->RoadWidth, 200.0);
	const double SW = FMath::Max(S->SidewalkWidth, 60.0);
	const double FZ = FMath::Clamp(S->FurnitureZoneWidth, 0.0, SW * 0.6);
	const double CH = FMath::Max(S->CurbHeight, 0.0);
	const double Zr = Z0 - CH;              // road level
	const double CW = FMath::Max(S->CrosswalkWidth, 120.0);
	const double SizeX = FMath::Max(Bounds.GetSize().X, 2.0 * (S->BlockSizeMin + RW));
	const double SizeY = FMath::Max(Bounds.GetSize().Y, 2.0 * (S->BlockSizeMin + RW));

	// --- lines ------------------------------------------------------------------------------
	TArray<double> X, Y;
	RandomLineSpacings(Rng, SizeX, S->BlockSizeMin, S->BlockSizeMax, RW, X);
	RandomLineSpacings(Rng, SizeY, S->BlockSizeMin, S->BlockSizeMax, RW, Y);
	// Jitter interior lines; keep order with a margin so blocks never collapse.
	const double JitterAmp = FMath::Clamp(S->StreetJitter, 0.0, 1.0) * 0.25 * S->BlockSizeMin;
	for (int32 i = 1; i + 1 < X.Num(); ++i) { X[i] = FMath::Clamp(X[i] + RammsPCG::RandRange(Rng, -JitterAmp, JitterAmp), X[i - 1] + RW + 2.0 * SW + 300.0, X[i + 1] - RW - 2.0 * SW - 300.0); }
	for (int32 j = 1; j + 1 < Y.Num(); ++j) { Y[j] = FMath::Clamp(Y[j] + RammsPCG::RandRange(Rng, -JitterAmp, JitterAmp), Y[j - 1] + RW + 2.0 * SW + 300.0, Y[j + 1] - RW - 2.0 * SW - 300.0); }
	for (double& V : X) { V += Centre.X; }
	for (double& V : Y) { V += Centre.Y; }
	const int32 NX = X.Num(), NY = Y.Num();
	if (NX < 2 || NY < 2)
	{
		PCGE_LOG(Warning, GraphAndLog, LOCTEXT("TooSmall", "Site too small for one block; nothing generated."));
		return true;
	}

	// --- segments and blocks ------------------------------------------------------------------
	TArray<FSeg> Segs;
	auto SegIndexX = [&](int32 i, int32 j) { return j * (NX - 1) + i; };               // X segments: i in [0,NX-2], j in [0,NY-1]
	auto SegIndexY = [&](int32 i, int32 j) { return (NX - 1) * NY + i * (NY - 1) + j; }; // Y segments: i in [0,NX-1], j in [0,NY-2]
	for (int32 j = 0; j < NY; ++j) for (int32 i = 0; i + 1 < NX; ++i) { FSeg& Sg = Segs.AddDefaulted_GetRef(); Sg.bAlongX = true; Sg.I = i; Sg.J = j; }
	for (int32 i = 0; i < NX; ++i) for (int32 j = 0; j + 1 < NY; ++j) { FSeg& Sg = Segs.AddDefaulted_GetRef(); Sg.bAlongX = false; Sg.I = i; Sg.J = j; }

	// Cells, then pairwise merges that drop the shared interior segment.
	TArray<int32> CellBlock; // cell (i,j) -> block index
	CellBlock.Init(-1, (NX - 1) * (NY - 1));
	auto Cell = [&](int32 i, int32 j) -> int32& { return CellBlock[j * (NX - 1) + i]; };
	TArray<FBlock> Blocks;
	const double Dropout = FMath::Clamp(S->StreetDropout, 0.0, 0.6);
	for (int32 j = 0; j + 1 < NY; ++j)
	{
		for (int32 i = 0; i + 1 < NX; ++i)
		{
			if (Cell(i, j) >= 0) { continue; }
			FBlock B; B.Id = Blocks.Num(); B.X0 = X[i]; B.X1 = X[i + 1]; B.Y0 = Y[j]; B.Y1 = Y[j + 1];
			Cell(i, j) = B.Id;
			if (Dropout > 0.0 && Rng.FRand() < Dropout)
			{
				// Merge with the unmerged neighbour to the east, else to the north.
				if (i + 2 < NX && Cell(i + 1, j) < 0)
				{
					Cell(i + 1, j) = B.Id; B.X1 = X[i + 2];
					Segs[SegIndexY(i + 1, j)].bLive = false;
				}
				else if (j + 2 < NY && Cell(i, j + 1) < 0)
				{
					Cell(i, j + 1) = B.Id; B.Y1 = Y[j + 2];
					Segs[SegIndexX(i, j + 1)].bLive = false;
				}
			}
			B.bPark = Rng.FRand() < FMath::Clamp(S->ParkFraction, 0.0, 1.0);
			B.bLawn = B.bPark || Rng.FRand() < FMath::Clamp(S->LawnLots, 0.0, 1.0);
			Blocks.Add(B);
		}
	}
	// A preset that asks for parks gets at least one when there is room for it, so a small site
	// with an unlucky seed still shows the park features it was built to show.
	if (S->ParkFraction > 0.0 && Blocks.Num() >= 3 && !Blocks.ContainsByPredicate([](const FBlock& B) { return B.bPark; }))
	{
		FBlock& B = Blocks[Rng.RandRange(0, Blocks.Num() - 1)];
		B.bPark = true; B.bLawn = true;
	}

	// --- sides -----------------------------------------------------------------------------------
	TArray<FSide> Sides;
	for (const FBlock& B : Blocks)
	{
		const double ox0 = B.X0 + RW * 0.5, ox1 = B.X1 - RW * 0.5, oy0 = B.Y0 + RW * 0.5, oy1 = B.Y1 - RW * 0.5;
		auto AddSide = [&](int32 Index, const FVector& Start, const FVector& Dir, const FVector& Inward, double Length, double Yaw)
		{
			FSide& Sd = Sides.AddDefaulted_GetRef();
			Sd.BlockId = B.Id; Sd.Index = Index; Sd.Start = Start; Sd.Dir = Dir; Sd.Inward = Inward; Sd.Length = Length; Sd.Yaw = Yaw;
		};
		AddSide(0, FVector(ox0, oy0, Z0), FVector(1, 0, 0), FVector(0, 1, 0), ox1 - ox0, 0.0);
		AddSide(1, FVector(ox1, oy0, Z0), FVector(0, 1, 0), FVector(-1, 0, 0), oy1 - oy0, 90.0);
		AddSide(2, FVector(ox1, oy1, Z0), FVector(-1, 0, 0), FVector(0, -1, 0), ox1 - ox0, 180.0);
		AddSide(3, FVector(ox0, oy1, Z0), FVector(0, -1, 0), FVector(1, 0, 0), oy1 - oy0, 270.0);
	}
	// Find the side of a block that faces a road line at a coordinate.
	auto FindSide = [&](bool bRoadAlongX, double Across, double Pos, bool bNegativeSide) -> FSide*
	{
		for (FSide& Sd : Sides)
		{
			const FBlock& B = Blocks[Sd.BlockId];
			if (bRoadAlongX)
			{
				// Road at y = Across. Negative side = block below (its north side, index 2); else block above (south, 0).
				const bool bMatch = bNegativeSide ? (Sd.Index == 2 && FMath::IsNearlyEqual(B.Y1, Across, 1.0)) : (Sd.Index == 0 && FMath::IsNearlyEqual(B.Y0, Across, 1.0));
				if (bMatch && Pos > B.X0 + RW * 0.5 + CW && Pos < B.X1 - RW * 0.5 - CW) { return &Sd; }
			}
			else
			{
				// Road at x = Across. Negative side = block to the left (east side, 1); else block to the right (west, 3).
				const bool bMatch = bNegativeSide ? (Sd.Index == 1 && FMath::IsNearlyEqual(B.X1, Across, 1.0)) : (Sd.Index == 3 && FMath::IsNearlyEqual(B.X0, Across, 1.0));
				if (bMatch && Pos > B.Y0 + RW * 0.5 + CW && Pos < B.Y1 - RW * 0.5 - CW) { return &Sd; }
			}
		}
		return nullptr;
	};
	auto AlongOnSide = [&](const FSide& Sd, const FVector& WorldPoint) -> double
	{
		return FVector::DotProduct(WorldPoint - Sd.Start, Sd.Dir);
	};

	// --- emit -------------------------------------------------------------------------------------
	FRammsPointWriter Primitives, Props, Pieces, BlocksOut, SidewalksOut, Features;
	const FString MatRoad = RammsPCG::Mat(Palette, RammsPaletteSlots::MatAsphalt);
	const FString MatWalk = RammsPCG::Mat(Palette, RammsPaletteSlots::MatSidewalk);
	const FString MatPaint = RammsPCG::Mat(Palette, RammsPaletteSlots::MatPaint);
	const FString MatMarking = RammsPCG::Mat(Palette, RammsPaletteSlots::MatMarking);
	const FString MatMarkingYellow = RammsPCG::Mat(Palette, RammsPaletteSlots::MatMarkingYellow);
	const FString MatWarn = RammsPCG::Mat(Palette, RammsPaletteSlots::MatWarning);
	const FString MatLawn = RammsPCG::Mat(Palette, RammsPaletteSlots::MatLawn);
	const FString MatConcrete = RammsPCG::Mat(Palette, RammsPaletteSlots::MatConcrete);
	const FString MatCurb = Palette && Palette->HasSlot(RammsPaletteSlots::MatCurb) ? RammsPCG::Mat(Palette, RammsPaletteSlots::MatCurb) : MatConcrete;
	int32 FeatureSeed = 0;
	auto NextSeed = [&]() { return RammsPCG::SubSeed(Seed, ++FeatureSeed); };

	const double RampWidth = FMath::Clamp(CW * 0.45, 100.0, 150.0);

	// Crossings: one near each end of every live segment, plus optional mid-block.
	auto EmitCrossing = [&](const FSeg& Sg, double Pos)
	{
		const bool bRoadAlongX = Sg.bAlongX;
		const double Across = bRoadAlongX ? Y[Sg.J] : X[Sg.I];
		// Zebra bars: long along the road (CW), stacked across the road from curb to curb.
		const double BarW = 40.0, Gap = 40.0;
		const int32 Bars = FMath::Max(1, FMath::FloorToInt((RW - 2.0 * 30.0) / (BarW + Gap)));
		const double Span = Bars * (BarW + Gap) - Gap;
		for (int32 b = 0; b < Bars; ++b)
		{
			const double Off = -Span * 0.5 + BarW * 0.5 + b * (BarW + Gap);
			const FVector C = bRoadAlongX ? FVector(Pos, Across + Off, Zr + 0.3) : FVector(Across + Off, Pos, Zr + 0.3);
			RammsPCG::WriteCube(Primitives, C, bRoadAlongX ? FVector(CW, BarW, 0.6) : FVector(BarW, CW, 0.6), 0.0, MatPaint, NextSeed());
		}
		// Curb ramps on both sides where a block exists.
		for (int32 k = 0; k < 2; ++k)
		{
			FSide* Sd = FindSide(bRoadAlongX, Across, Pos, k == 0);
			if (!Sd) { continue; }
			const FVector CurbPoint = bRoadAlongX ? FVector(Pos, Across + (k == 0 ? -RW * 0.5 : RW * 0.5), Z0) : FVector(Across + (k == 0 ? -RW * 0.5 : RW * 0.5), Pos, Z0);
			const double Along = AlongOnSide(*Sd, CurbPoint);
			if (Along < RampWidth || Along > Sd->Length - RampWidth) { continue; }

			const double Roll = Rng.FRand();
			const bool bBreak = Roll < S->NonCompliance;
			const double Sub = Rng.FRand();
			if (bBreak && Sub < 0.5)
			{
				// Missing curb ramp: the curb runs through. Record it; nothing to build.
				const int32 f = Features.AddBox(CurbPoint, Sd->Yaw, FVector(RampWidth, 20.0, CH), NextSeed());
				RammsPCG::WriteManifest(Features, f, FName(TEXT("Crossing")), FName(TEXT("MissingCurbRamp")), false, ERammsComplianceIssue::MissingCurbRamp, CH, S->VerticalChangeMax);
				continue;
			}
			FRammsPieceDesc P;
			P.Kind = ERammsProcPieceKind::CurbRamp;
			P.Rise = CH;
			P.SizeY = RampWidth;
			P.FlareSlope = S->CurbRampFlareSlope;
			P.MaterialPath = MatConcrete;
			P.MaterialPath2 = MatWarn;
			P.ManifestKind = FName(TEXT("CurbRamp"));
			P.Threshold = S->RampMaxSlope;
			P.Seed = NextSeed();
			if (bBreak && Sub < 0.85)
			{
				P.Slope = S->RampMaxSlope * RammsPCG::RandRange(Rng, 1.4, 2.4);
				P.WarningDepth = S->DetectableWarningDepth;
				P.bCompliant = false; P.Issue = ERammsComplianceIssue::SlopeTooSteep; P.ManifestSubtype = FName(TEXT("TooSteep"));
			}
			else if (bBreak)
			{
				P.Slope = S->RampMaxSlope;
				P.WarningDepth = 0.0; // compliant for a wheelchair, flagged for the record
				P.bCompliant = true; P.ManifestSubtype = FName(TEXT("NoDetectableWarning"));
			}
			else
			{
				P.Slope = S->RampMaxSlope;
				P.WarningDepth = S->DetectableWarningDepth;
				P.ManifestSubtype = FName(TEXT("Standard"));
			}
			P.Measure = P.Slope;
			const double Run = CH / P.Slope;
			// Ramp frame: +X points outward (descends to the road); origin at the top, Run inward from the curb.
			const FVector Origin = CurbPoint + Sd->Inward * Run;
			P.Transform = FTransform(FRotator(0.0, Sd->Yaw - 90.0, 0.0), Origin);
			RammsPCG::WritePiece(Pieces, P);
			Sd->Keepouts.Add(FVector2D(Along - RampWidth * 0.5 - 10.0, Along + RampWidth * 0.5 + 10.0));
			// Keep the landing in front of the ramp free of props/hazards too.
			(void)Run;
		}
	};

	for (const FSeg& Sg : Segs)
	{
		if (!Sg.bLive) { continue; }
		const double A = Sg.bAlongX ? X[Sg.I] : Y[Sg.J];
		const double B = Sg.bAlongX ? X[Sg.I + 1] : Y[Sg.J + 1];
		const double Across = Sg.bAlongX ? Y[Sg.J] : X[Sg.I];
		const double Len = B - A - RW; // between intersection squares
		// Road slab between the intersection squares.
		const FVector C = Sg.bAlongX ? FVector((A + B) * 0.5, Across, Zr - 10.0) : FVector(Across, (A + B) * 0.5, Zr - 10.0);
		RammsPCG::WriteCube(Primitives, C, Sg.bAlongX ? FVector(Len, RW, 20.0) : FVector(RW, Len, 20.0), 0.0, MatRoad, NextSeed());
		// Road wear: cracks, patches, manholes and the odd pothole, projected onto the asphalt.
		if (S->DecalDensity > 0.0 && Palette && Len > 300.0)
		{
			const int32 N = FMath::RoundToInt(S->DecalDensity * Len / 10000.0 + RammsPCG::RandRange(Rng, -0.4, 0.4));
			for (int32 n = 0; n < N; ++n)
			{
				const double Roll = Rng.FRand();
				const FName Slot = Roll < 0.45 ? RammsPaletteSlots::DecalRoadCrack : Roll < 0.7 ? RammsPaletteSlots::DecalPatch : Roll < 0.85 ? RammsPaletteSlots::DecalPothole : RammsPaletteSlots::DecalPuddle;
				const FString M = Palette->PickMaterialPath(Slot, Rng);
				if (M.IsEmpty()) { continue; }
				const double Sz = Slot == RammsPaletteSlots::DecalPothole ? RammsPCG::RandRange(Rng, 70.0, 140.0)
					: Slot == RammsPaletteSlots::DecalPatch ? RammsPCG::RandRange(Rng, 80.0, 170.0) : RammsPCG::RandRange(Rng, 150.0, 400.0);
				const double Along = RammsPCG::RandRange(Rng, A + RW * 0.5 + 100.0, B - RW * 0.5 - 100.0);
				const double AcrossD = RammsPCG::RandRange(Rng, -RW * 0.5 + Sz * 0.4, RW * 0.5 - Sz * 0.4);
				FRammsPieceDesc Dc;
				Dc.Kind = ERammsProcPieceKind::Decal;
				Dc.SizeX = Sz; Dc.SizeY = Sz * RammsPCG::RandRange(Rng, 0.5, 1.0); Dc.SizeZ = 40.0;
				Dc.MaterialPath = M;
				const FVector P = Sg.bAlongX ? FVector(Along, Y[Sg.J] + AcrossD, Zr) : FVector(X[Sg.I] + AcrossD, Along, Zr);
				Dc.Transform = FTransform(FRotator(0.0, RammsPCG::RandRange(Rng, 0.0, 360.0), 0.0), P);
				Dc.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, Dc);
			}
		}
		// Markings: a dashed yellow centre line between the crossings, white edge lines along the
		// gutters, and a stop line before each end of the segment.
		{
			const double a0 = A + RW * 0.5, b0 = B - RW * 0.5;
			const double Keep = CW + 120.0; // leave the crossings and stop lines clear
			auto Along = [&](double Pos, double Off, double LenAlong, double Wide, const FString& Mat)
			{
				const FVector P = Sg.bAlongX ? FVector(Pos, Across + Off, Zr + 0.3) : FVector(Across + Off, Pos, Zr + 0.3);
				RammsPCG::WriteCube(Primitives, P, Sg.bAlongX ? FVector(LenAlong, Wide, 0.6) : FVector(Wide, LenAlong, 0.6), 0.0, Mat, NextSeed());
			};
			if (RW >= 500.0)
			{
				for (double p = a0 + Keep; p + 300.0 <= b0 - Keep; p += 600.0) { Along(p + 150.0, 0.0, 300.0, 12.0, MatMarkingYellow); }
			}
			if (b0 - a0 > 2.0 * Keep + 200.0)
			{
				Along((a0 + b0) * 0.5, RW * 0.5 - 30.0, b0 - a0 - 2.0 * Keep, 10.0, MatMarking);
				Along((a0 + b0) * 0.5, -RW * 0.5 + 30.0, b0 - a0 - 2.0 * Keep, 10.0, MatMarking);
			}
			if (Len > 2.0 * CW + 400.0)
			{
				// Stop lines sit between the crossing and the intersection, on the approach half of the road.
				Along(a0 + CW + 95.0, -RW * 0.25, 30.0, RW * 0.5 - 40.0, MatMarking);
				Along(b0 - CW - 95.0, RW * 0.25, 30.0, RW * 0.5 - 40.0, MatMarking);
			}
		}
		// Crossings near both ends.
		if (Len > 2.0 * CW + 200.0)
		{
			EmitCrossing(Sg, A + RW * 0.5 + CW * 0.5 + 40.0);
			EmitCrossing(Sg, B - RW * 0.5 - CW * 0.5 - 40.0);
			if (Len > 3000.0 && Rng.FRand() < S->MidblockCrossingChance)
			{
				EmitCrossing(Sg, (A + B) * 0.5);
			}
		}
		else if (Len > CW)
		{
			EmitCrossing(Sg, (A + B) * 0.5);
		}
	}
	// Intersection squares at nodes touched by a live segment.
	for (int32 j = 0; j < NY; ++j)
	{
		for (int32 i = 0; i < NX; ++i)
		{
			bool bAny = false;
			if (i > 0) { bAny |= Segs[SegIndexX(i - 1, j)].bLive; }
			if (i + 1 < NX) { bAny |= Segs[SegIndexX(i, j)].bLive; }
			if (j > 0) { bAny |= Segs[SegIndexY(i, j - 1)].bLive; }
			if (j + 1 < NY) { bAny |= Segs[SegIndexY(i, j)].bLive; }
			if (bAny)
			{
				RammsPCG::WriteCube(Primitives, FVector(X[i], Y[j], Zr - 10.0), FVector(RW, RW, 20.0), 0.0, MatRoad, NextSeed());
			}
		}
	}
	// Road centrelines.
	for (int32 j = 0; j < NY; ++j) { RammsPCG::EmitSpline(Context, RammsPCG::PinRoads, { FVector(X[0], Y[j], Zr), FVector(X.Last(), Y[j], Zr) }, false, { TEXT("RoadX") }); }
	for (int32 i = 0; i < NX; ++i) { RammsPCG::EmitSpline(Context, RammsPCG::PinRoads, { FVector(X[i], Y[0], Zr), FVector(X[i], Y.Last(), Zr) }, false, { TEXT("RoadY") }); }

	// Sidewalk rings, curbs, blocks, sidewalk-side points.
	FRammsPaletteMesh CurbMesh;
	const bool bCurbMesh = Palette && Palette->PickMesh(RammsPaletteSlots::Curb, Rng, CurbMesh);
	const double CurbStep = bCurbMesh ? FMath::Max(CurbMesh.Footprint.X, 50.0) : 200.0;
	for (const FSide& Sd : Sides)
	{
		const FBlock& B = Blocks[Sd.BlockId];
		// Slab: east/west sides shortened by SW at both ends so corners are covered once.
		const bool bShort = (Sd.Index == 1 || Sd.Index == 3);
		const double L0 = bShort ? SW : 0.0;
		const double L = Sd.Length - (bShort ? 2.0 * SW : 0.0);
		const bool bStrip = S->PlantingStrip > 0.5 && FZ > 30.0 && !B.bPark;
		if (L > 1.0)
		{
			// A planting strip street: grass between the curb and the walk (paved where the curb ramps land).
			const double Pave0 = bStrip ? FZ : 0.0;
			const FVector SlabCentre = Sd.Start + Sd.Dir * (L0 + L * 0.5) + Sd.Inward * ((SW + Pave0) * 0.5) + FVector(0, 0, -10.0);
			RammsPCG::WriteCube(Primitives, SlabCentre, FVector(L, SW - Pave0, 20.0), Sd.Yaw, MatWalk, NextSeed());
			if (bStrip)
			{
				FRammsPieceDesc G;
				G.Kind = ERammsProcPieceKind::Slab;
				G.SizeX = L; G.SizeY = FZ; G.SizeZ = 20.0; G.UVScale = 350.0;
				G.MaterialPath = MatLawn;
				G.Transform = FTransform(FRotator(0.0, Sd.Yaw, 0.0), Sd.Start + Sd.Dir * L0 + Sd.Inward * (FZ * 0.5) + FVector(0, 0, -0.5));
				G.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, G);
				// (The lots dress the strip in front of them - trees, grass, lights - around their driveways.)
			}
		}
		// Sidewalk wear: cracks and stains projected onto the walk.
		if (S->DecalDensity > 0.0 && Palette && L > 200.0)
		{
			const int32 N = FMath::RoundToInt(S->DecalDensity * 0.8 * L / 10000.0 + RammsPCG::RandRange(Rng, -0.4, 0.4));
			for (int32 n = 0; n < N; ++n)
			{
				const bool bStain = Rng.FRand() < 0.35;
				const FString M = Palette->PickMaterialPath(bStain ? RammsPaletteSlots::DecalStain : RammsPaletteSlots::DecalWalkCrack, Rng);
				if (M.IsEmpty()) { continue; }
				const double Sz = RammsPCG::RandRange(Rng, 80.0, 200.0);
				const double Lo = bStrip ? FZ + Sz * 0.3 : Sz * 0.3, Hi = SW - Sz * 0.3;
				if (Hi <= Lo) { continue; }
				FRammsPieceDesc Dc;
				Dc.Kind = ERammsProcPieceKind::Decal;
				Dc.SizeX = Sz; Dc.SizeY = Sz * RammsPCG::RandRange(Rng, 0.5, 1.0); Dc.SizeZ = 40.0;
				Dc.MaterialPath = M;
				Dc.Transform = FTransform(FRotator(0.0, RammsPCG::RandRange(Rng, 0.0, 360.0), 0.0), Sd.Start + Sd.Dir * RammsPCG::RandRange(Rng, L0 + 60.0, L0 + L - 60.0) + Sd.Inward * RammsPCG::RandRange(Rng, Lo, Hi));
				Dc.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, Dc);
			}
		}
		// Parked cars at the curb (in the road, outside the curb line), clear of crossings and ramps.
		if (S->ParkingDensity > 0.0 && RW >= 550.0 && Sd.Length > 1500.0)
		{
			FRammsPaletteMesh CarMesh;
			if (Palette && Palette->PickMesh(RammsPaletteSlots::Car, Rng, CarMesh))
			{
				const double CarL = FMath::Max(CarMesh.Footprint.X, 380.0), CarW = FMath::Max(CarMesh.Footprint.Y, 160.0);
				for (double a = CW + 260.0 + CarL * 0.5; a < Sd.Length - CW - 260.0 - CarL * 0.5; a += CarL + RammsPCG::RandRange(Rng, 120.0, 320.0))
				{
					if (Rng.FRand() > FMath::Clamp(S->ParkingDensity, 0.0, 1.0)) { continue; }
					bool bSkip = false;
					for (const FVector2D& K : Sd.Keepouts) { if (a + CarL * 0.5 > K.X - 60.0 && a - CarL * 0.5 < K.Y + 60.0) { bSkip = true; break; } }
					if (bSkip) { continue; }
					FRammsPaletteMesh Pick;
					if (!Palette->PickMesh(RammsPaletteSlots::Car, Rng, Pick)) { break; }
					const FVector P = Sd.Start + Sd.Dir * a - Sd.Inward * (FMath::Max(Pick.Footprint.Y, 160.0) * 0.5 + 25.0) + FVector(0, 0, Zr - Z0);
					const int32 c = RammsPCG::WritePickedMesh(Props, Pick, P, Sd.Yaw + (Rng.FRand() < 0.5 ? 0.0 : 180.0), NextSeed());
					RammsPCG::WriteManifest(Props, c, FName(TEXT("Vehicle")), FName(TEXT("Parked")), true, ERammsComplianceIssue::None, 0.0, 0.0);
				}
			}
		}
		// Curbs along the curb line, skipping ramp keepouts: one mesh per step when the palette has a curb
		// mesh, otherwise one continuous procedural piece per uninterrupted run.
		if (bCurbMesh)
		{
			for (double a = CurbStep * 0.5; a < Sd.Length; a += CurbStep)
			{
				bool bSkip = false;
				for (const FVector2D& K : Sd.Keepouts) { if (a > K.X - CurbStep * 0.5 && a < K.Y + CurbStep * 0.5) { bSkip = true; break; } }
				if (bSkip) { continue; }
				RammsPCG::WritePaletteMesh(Props, Palette, RammsPaletteSlots::Curb, Rng, Sd.Start + Sd.Dir * a + FVector(0, 0, -CH), Sd.Yaw, NextSeed());
			}
		}
		else
		{
			TArray<FVector2D> Cuts = Sd.Keepouts;
			Cuts.Sort([](const FVector2D& A, const FVector2D& B) { return A.X < B.X; });
			double RunStart = 0.0;
			auto EmitRun = [&](double A0, double A1)
			{
				if (A1 - A0 < 20.0) { return; }
				FRammsPieceDesc P2;
				P2.Kind = ERammsProcPieceKind::Curb; P2.SizeX = A1 - A0; P2.SizeY = 20.0; P2.Rise = CH; P2.MaterialPath = MatCurb; P2.Seed = NextSeed();
				P2.Transform = FTransform(FRotator(0.0, Sd.Yaw, 0.0), Sd.Start + Sd.Dir * A0);
				RammsPCG::WritePiece(Pieces, P2);
			};
			for (const FVector2D& K : Cuts)
			{
				EmitRun(RunStart, FMath::Clamp(K.X, RunStart, Sd.Length));
				RunStart = FMath::Max(RunStart, FMath::Min(K.Y, Sd.Length));
			}
			EmitRun(RunStart, Sd.Length);
		}
		// Side point for the hazard placer.
		const int32 s = SidewalksOut.Add(FTransform(FRotator(0.0, Sd.Yaw, 0.0), Sd.Start), FVector(0.0, 0.0, 0.0), FVector(Sd.Length, SW, 0.0), NextSeed());
		SidewalksOut.SetInt(s, RammsPCG::BlockId, B.Id);
		SidewalksOut.SetInt(s, RammsPCG::Side, Sd.Index);
		SidewalksOut.Set(s, RammsPCG::Length, Sd.Length);
		SidewalksOut.Set(s, RammsPCG::Width, SW);
		SidewalksOut.Set(s, RammsPCG::FurnitureZone, FZ);
		SidewalksOut.Set(s, RammsPCG::RouteWidth, SW - FZ);
		SidewalksOut.SetBool(s, RammsPCG::IsPark, B.bPark);
		FString Keep;
		for (const FVector2D& K : Sd.Keepouts) { Keep += FString::Printf(TEXT("%.0f-%.0f;"), K.X, K.Y); }
		SidewalksOut.Set(s, FName(TEXT("Keepouts")), Keep);
		SidewalksOut.Set(s, RammsPCG::RouteName, FName(*FString::Printf(TEXT("Block%d_Side%d"), B.Id, Sd.Index)));
	}
	for (const FBlock& B : Blocks)
	{
		const double lx0 = B.X0 + RW * 0.5 + SW, lx1 = B.X1 - RW * 0.5 - SW, ly0 = B.Y0 + RW * 0.5 + SW, ly1 = B.Y1 - RW * 0.5 - SW;
		const FVector LotCentre((lx0 + lx1) * 0.5, (ly0 + ly1) * 0.5, Z0);
		const FVector LotSize(lx1 - lx0, ly1 - ly0, 0.0);
		const int32 b = BlocksOut.Add(FTransform(LotCentre), -LotSize * 0.5, LotSize * 0.5, RammsPCG::SubSeed(Seed, 1000 + B.Id));
		BlocksOut.SetInt(b, RammsPCG::BlockId, B.Id);
		BlocksOut.SetBool(b, RammsPCG::IsPark, B.bPark);
		BlocksOut.Set(b, RammsPCG::Width, LotSize.X);
		BlocksOut.Set(b, RammsPCG::Depth, LotSize.Y);
		// Ground inside the block: lawn for parks and yards, concrete for built blocks (buildings sit on
		// it). A slab piece rather than a scaled cube so the material tiles at a sensible size.
		{
			FRammsPieceDesc G;
			G.Kind = ERammsProcPieceKind::Slab;
			G.SizeX = LotSize.X; G.SizeY = LotSize.Y; G.SizeZ = 20.0;
			G.UVScale = B.bLawn ? 350.0 : 250.0;
			G.MaterialPath = B.bLawn ? MatLawn : MatConcrete;
			G.Transform = FTransform(FRotator::ZeroRotator, FVector(lx0, LotCentre.Y, Z0)); // slab top sits at its pivot
			G.Seed = NextSeed();
			RammsPCG::WritePiece(Pieces, G);
		}
	}

	Primitives.Emit(Context, RammsPCG::PinPrimitives, { TEXT("Street") });
	Props.Emit(Context, RammsPCG::PinProps, { TEXT("Curb") });
	Pieces.Emit(Context, RammsPCG::PinPieces, { TEXT("Street") });
	BlocksOut.Emit(Context, RammsPCG::PinBlocks);
	SidewalksOut.Emit(Context, RammsPCG::PinSidewalks);
	Features.Emit(Context, RammsPCG::PinFeatures);
	return true;
}

#undef LOCTEXT_NAMESPACE
