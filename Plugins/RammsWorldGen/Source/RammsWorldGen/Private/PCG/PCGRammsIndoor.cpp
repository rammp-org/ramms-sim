// Copyright ATDev. All Rights Reserved.
#include "PCG/PCGRammsIndoor.h"

#include "PCGContext.h"
#include "RammsWorldGenModule.h"
#include "PCGPin.h"
#include "Algo/Reverse.h"

#define LOCTEXT_NAMESPACE "RammsPCG"

TArray<FPCGPinProperties> UPCGRammsIndoorLayoutSettings::InputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace_GetRef(RammsPCG::PinIn, EPCGDataType::Spatial, false, false, LOCTEXT("IndoorIn", "The generator's bounds (Input node In pin)")).SetRequiredPin();
	return Pins;
}

TArray<FPCGPinProperties> UPCGRammsIndoorLayoutSettings::OutputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace(RammsPCG::PinPieces, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinPrimitives, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinProps, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinRoutes, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinFeatures, EPCGDataType::Point);
	return Pins;
}

FPCGElementPtr UPCGRammsIndoorLayoutSettings::CreateElement() const
{
	return MakeShared<FPCGRammsIndoorLayoutElement>();
}

namespace
{
	struct FRoom
	{
		int32 Id = 0;
		FBox2D Rect;
		FName Kind;
		bool bCorridor = false;
		TArray<FVector2D> DoorCentres; // doors on this room's walls
		TArray<double> DoorWidths;     // parallel to DoorCentres
		TArray<FBox2D> Keepouts;       // door swings and approaches: nothing is placed here
		FString WallMat, WallMatLow, FloorMat; // finishes picked per room (WallMatLow: wainscot below 120 cm)
	};

	// A wall between two rooms (or a room and the outside), as a segment on a dividing line.
	struct FWallSeg
	{
		int32 RoomA = -1, RoomB = -1; // -1 = exterior
		bool bAlongX = true;           // the wall runs along X at y = Line
		double Line = 0.0;
		double A = 0.0, B = 0.0;       // extent along the wall
		bool bHasDoor = false;
		double DoorAt = 0.0;           // along-position of the door centre when bHasDoor
		double DoorWidth = 0.0;
		TArray<FVector4> Windows;      // exterior walls: (centre along, width, sill, head)
	};

	struct FFurnitureRule { FName Slot; bool bAgainstWall; double Weight; };

	FName KindForRoom(const FRandomStream& Rng, double Area, bool bSmallest, double OfficeFraction, double RetailFraction)
	{
		if (bSmallest) { return FName(TEXT("Bathroom")); }
		if (RetailFraction > 0.0 && Rng.FRand() < RetailFraction)
		{
			return Area > 30.0 * 10000.0 ? FName(TEXT("Shop")) : FName(TEXT("Storage"));
		}
		const double R = Rng.FRand();
		if (Rng.FRand() < OfficeFraction)
		{
			// Workplace: offices, meeting rooms (a table and chairs) and a break room (a kitchen).
			if (Area > 30.0 * 10000.0) { return R < 0.5 ? FName(TEXT("Meeting")) : FName(TEXT("Office")); }
			if (R < 0.7) { return FName(TEXT("Office")); }
			if (R < 0.85) { return FName(TEXT("Meeting")); }
			return FName(TEXT("Kitchen"));
		}
		if (Area > 25.0 * 10000.0) { return R < 0.6 ? FName(TEXT("Living")) : FName(TEXT("Dining")); }
		if (R < 0.35) { return FName(TEXT("Bedroom")); }
		if (R < 0.6) { return FName(TEXT("Office")); }
		if (R < 0.8) { return FName(TEXT("Kitchen")); }
		return FName(TEXT("Living"));
	}

	int32 Find(TArray<int32>& Parent, int32 x) { while (Parent[x] != x) { Parent[x] = Parent[Parent[x]]; x = Parent[x]; } return x; }
}

bool FPCGRammsIndoorLayoutElement::ExecuteInternal(FPCGContext* Context) const
{
	const UPCGRammsIndoorLayoutSettings* S = Context->GetInputSettings<UPCGRammsIndoorLayoutSettings>();
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
	const FString MatWall = RammsPCG::Mat(Palette, RammsPaletteSlots::MatWallInterior);
	const FString MatDoor = RammsPCG::Mat(Palette, RammsPaletteSlots::MatDoor);
	const FString MatMetal = RammsPCG::Mat(Palette, RammsPaletteSlots::MatMetal);
	const FString MatWood = RammsPCG::Mat(Palette, RammsPaletteSlots::MatFloorWood);
	const FString MatTile = RammsPCG::Mat(Palette, RammsPaletteSlots::MatFloorTile);
	const FString MatCarpet = RammsPCG::Mat(Palette, RammsPaletteSlots::MatFloorCarpet);

	const FBox Bounds = RammsPCG::InputBounds(Context, RammsPCG::PinIn, FVector(S->SiteSizeX, S->SiteSizeY, 600.0));
	const FVector C = Bounds.GetCenter();
	const double Z0 = C.Z;
	const double T = FMath::Clamp(S->WallThickness, 5.0, 60.0);
	const double H = FMath::Max(S->WallHeight, 200.0);
	const double RMin = FMath::Max(S->RoomSizeMin, 200.0);
	const double RMax = FMath::Max(S->RoomSizeMax, RMin + 50.0);
	const FBox2D Site(FVector2D(C.X - Bounds.GetSize().X * 0.5 + T, C.Y - Bounds.GetSize().Y * 0.5 + T), FVector2D(C.X + Bounds.GetSize().X * 0.5 - T, C.Y + Bounds.GetSize().Y * 0.5 - T));

	// --- rooms ----------------------------------------------------------------------------------
	TArray<FRoom> Rooms;
	auto AddRoom = [&](const FBox2D& Rect, bool bCorridor) { FRoom& R = Rooms.AddDefaulted_GetRef(); R.Id = Rooms.Num() - 1; R.Rect = Rect; R.bCorridor = bCorridor; return R.Id; };
	auto SplitStrip = [&](const FBox2D& Strip, bool bAlongX)
	{
		// Cut a strip into rooms of size [RMin, RMax] along its long axis.
		const double Lo = bAlongX ? Strip.Min.X : Strip.Min.Y;
		const double Hi = bAlongX ? Strip.Max.X : Strip.Max.Y;
		double p = Lo;
		while (Hi - p > RMin * 0.5)
		{
			double W = RammsPCG::RandRange(Rng, RMin, RMax);
			if (Hi - (p + W) < RMin * 0.7) { W = Hi - p; }
			FBox2D R = Strip;
			if (bAlongX) { R.Min.X = p; R.Max.X = p + W; } else { R.Min.Y = p; R.Max.Y = p + W; }
			AddRoom(R, false);
			p += W;
		}
	};
	const bool bCorridorPlan = Rng.FRand() < FMath::Clamp(S->CorridorChance, 0.0, 1.0) && FMath::Min(Site.GetSize().X, Site.GetSize().Y) > S->CorridorWidth + 2.0 * RMin;
	if (bCorridorPlan)
	{
		const bool bAlongX = Site.GetSize().X >= Site.GetSize().Y;
		const double CW = FMath::Max(S->CorridorWidth, 100.0);
		const FVector2D Mid = Site.GetCenter();
		if (bAlongX)
		{
			AddRoom(FBox2D(FVector2D(Site.Min.X, Mid.Y - CW * 0.5), FVector2D(Site.Max.X, Mid.Y + CW * 0.5)), true);
			SplitStrip(FBox2D(Site.Min, FVector2D(Site.Max.X, Mid.Y - CW * 0.5)), true);
			SplitStrip(FBox2D(FVector2D(Site.Min.X, Mid.Y + CW * 0.5), Site.Max), true);
		}
		else
		{
			AddRoom(FBox2D(FVector2D(Mid.X - CW * 0.5, Site.Min.Y), FVector2D(Mid.X + CW * 0.5, Site.Max.Y)), true);
			SplitStrip(FBox2D(Site.Min, FVector2D(Mid.X - CW * 0.5, Site.Max.Y)), false);
			SplitStrip(FBox2D(FVector2D(Mid.X + CW * 0.5, Site.Min.Y), Site.Max), false);
		}
	}
	else
	{
		// BSP: split the longer axis while a split leaves both halves >= RMin, stop at <= RMax.
		TArray<FBox2D> Stack; Stack.Add(Site);
		int32 Guard = 0;
		while (Stack.Num() > 0 && Guard++ < 500)
		{
			const FBox2D R = Stack.Pop();
			const FVector2D Sz = R.GetSize();
			const bool bAlongX = Sz.X >= Sz.Y;
			const double L = bAlongX ? Sz.X : Sz.Y;
			if (L <= RMax || L < 2.0 * RMin)
			{
				AddRoom(R, false);
				continue;
			}
			const double Cut = RammsPCG::RandRange(Rng, RMin, L - RMin);
			FBox2D A = R, B = R;
			if (bAlongX) { A.Max.X = R.Min.X + Cut; B.Min.X = R.Min.X + Cut; } else { A.Max.Y = R.Min.Y + Cut; B.Min.Y = R.Min.Y + Cut; }
			Stack.Add(A); Stack.Add(B);
		}
	}
	if (Rooms.Num() == 0)
	{
		AddRoom(Site, false);
	}
	// Kinds: smallest non-corridor room is the bathroom.
	{
		int32 Smallest = -1; double SmallestArea = TNumericLimits<double>::Max();
		for (const FRoom& R : Rooms) { if (!R.bCorridor && R.Rect.GetArea() < SmallestArea) { SmallestArea = R.Rect.GetArea(); Smallest = R.Id; } }
		for (FRoom& R : Rooms) { R.Kind = R.bCorridor ? FName(TEXT("Corridor")) : KindForRoom(Rng, R.Rect.GetArea(), R.Id == Smallest && Rooms.Num() > 2, FMath::Clamp(S->OfficeFraction, 0.0, 1.0), FMath::Clamp(S->RetailFraction, 0.0, 1.0)); }
	}

	// --- walls between rooms, and doors -------------------------------------------------------------
	TArray<FWallSeg> Walls;
	const double Tol = 1.0;
	for (int32 a = 0; a < Rooms.Num(); ++a)
	{
		for (int32 b = a + 1; b < Rooms.Num(); ++b)
		{
			const FBox2D& RA = Rooms[a].Rect; const FBox2D& RB = Rooms[b].Rect;
			// Vertical shared edge (wall along Y at x = line).
			if (FMath::IsNearlyEqual(RA.Max.X, RB.Min.X, Tol) || FMath::IsNearlyEqual(RB.Max.X, RA.Min.X, Tol))
			{
				const double Lo = FMath::Max(RA.Min.Y, RB.Min.Y), Hi = FMath::Min(RA.Max.Y, RB.Max.Y);
				if (Hi - Lo > 60.0) { FWallSeg& W = Walls.AddDefaulted_GetRef(); W.RoomA = a; W.RoomB = b; W.bAlongX = false; W.Line = FMath::IsNearlyEqual(RA.Max.X, RB.Min.X, Tol) ? RA.Max.X : RB.Max.X; W.A = Lo; W.B = Hi; }
			}
			// Horizontal shared edge (wall along X at y = line).
			if (FMath::IsNearlyEqual(RA.Max.Y, RB.Min.Y, Tol) || FMath::IsNearlyEqual(RB.Max.Y, RA.Min.Y, Tol))
			{
				const double Lo = FMath::Max(RA.Min.X, RB.Min.X), Hi = FMath::Min(RA.Max.X, RB.Max.X);
				if (Hi - Lo > 60.0) { FWallSeg& W = Walls.AddDefaulted_GetRef(); W.RoomA = a; W.RoomB = b; W.bAlongX = true; W.Line = FMath::IsNearlyEqual(RA.Max.Y, RB.Min.Y, Tol) ? RA.Max.Y : RB.Max.Y; W.A = Lo; W.B = Hi; }
			}
		}
	}
	// Doors: a spanning tree over room adjacency plus a few extras, each on a shared wall.
	{
		TArray<int32> Order; for (int32 i = 0; i < Walls.Num(); ++i) { Order.Add(i); }
		for (int32 i = Order.Num() - 1; i > 0; --i) { Order.Swap(i, Rng.RandRange(0, i)); }
		TArray<int32> Parent; for (int32 i = 0; i < Rooms.Num(); ++i) { Parent.Add(i); }
		auto AddDoor = [&](FWallSeg& W)
		{
			double Width = RammsPCG::RandNormal(Rng, S->DoorWidthMean, S->DoorWidthStd);
			if (Rng.FRand() < S->NonCompliance * 0.6) { Width = RammsPCG::RandRange(Rng, 60.0, S->DoorClearWidth - 1.5); }
			W.DoorWidth = FMath::Clamp(Width, 55.0, 120.0);
			W.DoorAt = RammsPCG::RandRange(Rng, W.A + 60.0 + W.DoorWidth * 0.5, W.B - 60.0 - W.DoorWidth * 0.5);
			W.bHasDoor = true;
			const FVector2D DoorC = W.bAlongX ? FVector2D(W.DoorAt, W.Line) : FVector2D(W.Line, W.DoorAt);
			Rooms[W.RoomA].DoorCentres.Add(DoorC); Rooms[W.RoomA].DoorWidths.Add(W.DoorWidth);
			Rooms[W.RoomB].DoorCentres.Add(DoorC); Rooms[W.RoomB].DoorWidths.Add(W.DoorWidth);
			Parent[Find(Parent, W.RoomA)] = Find(Parent, W.RoomB);
		};
		for (int32 wi : Order)
		{
			FWallSeg& W = Walls[wi];
			if (W.B - W.A < 150.0) { continue; }
			const bool bNeeded = Find(Parent, W.RoomA) != Find(Parent, W.RoomB);
			const bool bCorridorSide = Rooms[W.RoomA].bCorridor || Rooms[W.RoomB].bCorridor;
			if (!bNeeded && !(bCorridorSide && Rng.FRand() < 0.9) && Rng.FRand() > 0.15) { continue; }
			AddDoor(W);
		}
		// Every room must be reachable: connect any component still cut off through its longest wall.
		for (int32 Guard = 0; Guard < Rooms.Num(); ++Guard)
		{
			int32 BestWall = -1; double BestLen = 0.0;
			for (int32 wi = 0; wi < Walls.Num(); ++wi)
			{
				const FWallSeg& W = Walls[wi];
				if (W.bHasDoor || Find(Parent, W.RoomA) == Find(Parent, W.RoomB)) { continue; }
				if (W.B - W.A > BestLen) { BestLen = W.B - W.A; BestWall = wi; }
			}
			if (BestWall < 0 || BestLen < 150.0) { break; }
			AddDoor(Walls[BestWall]);
		}
		{
			int32 Components = 0;
			for (int32 i = 0; i < Rooms.Num(); ++i) { Components += Find(Parent, i) == i ? 1 : 0; }
			int32 Doored = 0; for (const FWallSeg& W : Walls) { Doored += W.bHasDoor ? 1 : 0; }
			UE_LOG(LogRammsWorldGen, Log, TEXT("%s: %d rooms, %d walls, %d doors, %d components after doors"), *S->GetName(), Rooms.Num(), Walls.Num(), Doored, Components);
			if (Components > 1)
			{
				UE_LOG(LogRammsWorldGen, Warning, TEXT("%s: %d rooms are not reachable (walls too short for a door)"), *S->GetName(), Components - 1);
			}
		}
	}
	// The leaf swings into room A (a DoorWidth square from the hinge) and both rooms keep an approach
	// strip in front of the opening free, so furniture never blocks a door or its swing.
	auto AddDoorKeepouts = [&](const FWallSeg& W)
	{
		const double DW = W.DoorWidth;
		const FVector2D ACentre = Rooms[W.RoomA].Rect.GetCenter();
		const double IntoA = W.bAlongX ? (ACentre.Y > W.Line ? 1.0 : -1.0) : (ACentre.X > W.Line ? 1.0 : -1.0);
		auto Strip = [&](double Depth, double Dir, double Widen) -> FBox2D
		{
			const double a0 = W.DoorAt - DW * 0.5 - Widen, a1 = W.DoorAt + DW * 0.5 + Widen;
			const double d0 = FMath::Min(W.Line, W.Line + Dir * Depth), d1 = FMath::Max(W.Line, W.Line + Dir * Depth);
			return W.bAlongX ? FBox2D(FVector2D(a0, d0), FVector2D(a1, d1)) : FBox2D(FVector2D(d0, a0), FVector2D(d1, a1));
		};
		Rooms[W.RoomA].Keepouts.Add(Strip(DW + 10.0, IntoA, 10.0));
		Rooms[W.RoomA].Keepouts.Add(Strip(FMath::Max(S->PreferredClearWidth, 120.0), IntoA, 15.0));
		if (W.RoomB >= 0)
		{
			Rooms[W.RoomB].Keepouts.Add(Strip(FMath::Max(S->PreferredClearWidth, 120.0), -IntoA, 15.0));
		}
	};
	for (const FWallSeg& W : Walls) { if (W.bHasDoor) { AddDoorKeepouts(W); } }
	// Exterior walls, one of them with the entrance: into the corridor when there is one, else the largest room.
	{
		const int32 FirstExterior = Walls.Num();
		FWallSeg& W1 = Walls.AddDefaulted_GetRef(); W1.bAlongX = true;  W1.Line = Site.Min.Y - T * 0.5; W1.A = Site.Min.X - T; W1.B = Site.Max.X + T;
		FWallSeg& W2 = Walls.AddDefaulted_GetRef(); W2.bAlongX = true;  W2.Line = Site.Max.Y + T * 0.5; W2.A = Site.Min.X - T; W2.B = Site.Max.X + T;
		FWallSeg& W3 = Walls.AddDefaulted_GetRef(); W3.bAlongX = false; W3.Line = Site.Min.X - T * 0.5; W3.A = Site.Min.Y; W3.B = Site.Max.Y;
		FWallSeg& W4 = Walls.AddDefaulted_GetRef(); W4.bAlongX = false; W4.Line = Site.Max.X + T * 0.5; W4.A = Site.Min.Y; W4.B = Site.Max.Y;

		int32 EntryRoom = -1; double Best = -1.0;
		for (const FRoom& R : Rooms)
		{
			const bool bTouches = FMath::IsNearlyEqual(R.Rect.Min.Y, Site.Min.Y, Tol) || FMath::IsNearlyEqual(R.Rect.Max.Y, Site.Max.Y, Tol) || FMath::IsNearlyEqual(R.Rect.Min.X, Site.Min.X, Tol) || FMath::IsNearlyEqual(R.Rect.Max.X, Site.Max.X, Tol);
			if (!bTouches) { continue; }
			const double Score = (R.bCorridor ? 1e9 : 0.0) + R.Rect.GetArea();
			if (Score > Best) { Best = Score; EntryRoom = R.Id; }
		}
		if (EntryRoom >= 0)
		{
			const FRoom& R = Rooms[EntryRoom];
			TArray<int32> Candidates;
			if (FMath::IsNearlyEqual(R.Rect.Min.Y, Site.Min.Y, Tol) && R.Rect.GetSize().X > 150.0) { Candidates.Add(FirstExterior + 0); }
			if (FMath::IsNearlyEqual(R.Rect.Max.Y, Site.Max.Y, Tol) && R.Rect.GetSize().X > 150.0) { Candidates.Add(FirstExterior + 1); }
			if (FMath::IsNearlyEqual(R.Rect.Min.X, Site.Min.X, Tol) && R.Rect.GetSize().Y > 150.0) { Candidates.Add(FirstExterior + 2); }
			if (FMath::IsNearlyEqual(R.Rect.Max.X, Site.Max.X, Tol) && R.Rect.GetSize().Y > 150.0) { Candidates.Add(FirstExterior + 3); }
			if (Candidates.Num() > 0)
			{
				FWallSeg& W = Walls[Candidates[Rng.RandRange(0, Candidates.Num() - 1)]];
				W.RoomA = EntryRoom; W.RoomB = -1;
				double Width = S->DoorClearWidth + RammsPCG::RandRange(Rng, 5.0, 15.0);
				if (Rng.FRand() < S->NonCompliance * 0.4) { Width = RammsPCG::RandRange(Rng, 65.0, S->DoorClearWidth - 1.5); }
				W.DoorWidth = FMath::Clamp(Width, 55.0, 120.0);
				const double Lo = (W.bAlongX ? R.Rect.Min.X : R.Rect.Min.Y) + 50.0 + W.DoorWidth * 0.5;
				const double Hi = (W.bAlongX ? R.Rect.Max.X : R.Rect.Max.Y) - 50.0 - W.DoorWidth * 0.5;
				W.DoorAt = RammsPCG::RandRange(Rng, Lo, Hi);
				W.bHasDoor = true;
				Rooms[EntryRoom].DoorCentres.Add(W.bAlongX ? FVector2D(W.DoorAt, W.Line) : FVector2D(W.Line, W.DoorAt));
				Rooms[EntryRoom].DoorWidths.Add(W.DoorWidth);
				AddDoorKeepouts(W);
			}
		}
	}

	// --- emit ------------------------------------------------------------------------------------------
	FRammsPointWriter Pieces, Primitives, Props, Routes, Features;
	int32 Counter = 0;
	auto NextSeed = [&]() { return RammsPCG::SubSeed(Seed, 8000 + (++Counter)); };
	const double PThreshold = FMath::Clamp(S->ThresholdChance * FMath::Min(1.0, S->NonCompliance * 4.0), 0.0, 1.0);

	// --- finishes and windows ---------------------------------------------------------------------
	const FString MatTrim = RammsPCG::Mat(Palette, RammsPaletteSlots::MatTrim);
	const FString MatTrimIn = Palette && Palette->HasSlot(FName(TEXT("Mat.Trim.Interior"))) ? RammsPCG::Mat(Palette, FName(TEXT("Mat.Trim.Interior"))) : MatTrim;
	const FString MatGlass = RammsPCG::Mat(Palette, RammsPaletteSlots::MatGlass);
	const FString MatConcreteFloor = RammsPCG::Mat(Palette, RammsPaletteSlots::MatConcrete);
	auto PickMat = [&](FName Slot, const FString& Fallback) -> FString
	{
		const FString M = Palette ? Palette->PickMaterialPath(Slot, Rng) : FString();
		return M.IsEmpty() ? Fallback : M;
	};
	for (FRoom& R : Rooms)
	{
		const FName K = R.Kind;
		const bool bHome = K == FName(TEXT("Living")) || K == FName(TEXT("Bedroom")) || K == FName(TEXT("Dining"));
		R.WallMat = (bHome && Rng.FRand() < 0.3) ? PickMat(RammsPaletteSlots::MatWallPaper, MatWall) : PickMat(RammsPaletteSlots::MatWallPaint, MatWall);
		if (K == FName(TEXT("Bathroom")) || (K == FName(TEXT("Kitchen")) && Rng.FRand() < 0.5)) { R.WallMatLow = PickMat(RammsPaletteSlots::MatWallTile, R.WallMat); }
		if (K == FName(TEXT("Bathroom")) || K == FName(TEXT("Kitchen"))) { R.FloorMat = PickMat(RammsPaletteSlots::MatFloorTile, MatTile); }
		else if (K == FName(TEXT("Shop"))) { R.FloorMat = PickMat(Rng.FRand() < 0.6 ? RammsPaletteSlots::MatFloorVinyl : RammsPaletteSlots::MatFloorTile, MatTile); }
		else if (K == FName(TEXT("Storage"))) { R.FloorMat = MatConcreteFloor; }
		else if (K == FName(TEXT("Bedroom"))) { R.FloorMat = Rng.FRand() < 0.55 ? PickMat(RammsPaletteSlots::MatFloorCarpet, MatCarpet) : PickMat(RammsPaletteSlots::MatFloorWood, MatWood); }
		else if (K == FName(TEXT("Office")) || K == FName(TEXT("Meeting"))) { R.FloorMat = Rng.FRand() < 0.6 ? PickMat(RammsPaletteSlots::MatFloorCarpet, MatCarpet) : PickMat(RammsPaletteSlots::MatFloorVinyl, MatTile); }
		else if (R.bCorridor) { R.FloorMat = Rng.FRand() < 0.5 ? PickMat(RammsPaletteSlots::MatFloorVinyl, MatTile) : PickMat(RammsPaletteSlots::MatFloorWood, MatWood); }
		else { R.FloorMat = PickMat(RammsPaletteSlots::MatFloorWood, MatWood); }
	}
	// Windows along the exterior walls, a few per room that touches them (none in storage or corridors),
	// kept clear of the entrance and of the interior walls that meet the facade.
	for (FWallSeg& W : Walls)
	{
		if (W.RoomB >= 0) { continue; }
		for (const FRoom& R : Rooms)
		{
			if (R.bCorridor || R.Kind == FName(TEXT("Storage"))) { continue; }
			const bool bTouch = W.bAlongX
				? (FMath::IsNearlyEqual(R.Rect.Min.Y, W.Line + T * 0.5, 2.0) || FMath::IsNearlyEqual(R.Rect.Max.Y, W.Line - T * 0.5, 2.0))
				: (FMath::IsNearlyEqual(R.Rect.Min.X, W.Line + T * 0.5, 2.0) || FMath::IsNearlyEqual(R.Rect.Max.X, W.Line - T * 0.5, 2.0));
			if (!bTouch) { continue; }
			const double Ra = FMath::Max(W.bAlongX ? R.Rect.Min.X : R.Rect.Min.Y, W.A), Rb = FMath::Min(W.bAlongX ? R.Rect.Max.X : R.Rect.Max.Y, W.B);
			const double Len = Rb - Ra;
			const bool bBath = R.Kind == FName(TEXT("Bathroom"));
			const bool bShop = R.Kind == FName(TEXT("Shop"));
			const double Ww = bBath ? 60.0 : (bShop ? 180.0 : RammsPCG::RandRange(Rng, 100.0, 140.0));
			const double Sill = bBath ? 140.0 : (bShop ? 60.0 : 90.0), Head = FMath::Min(210.0, H - 25.0);
			const int32 N = bBath ? 1 : FMath::Clamp(static_cast<int32>((Len - 60.0) / (bShop ? 360.0 : 300.0)), Len >= Ww + 100.0 ? 1 : 0, 4);
			for (int32 k = 0; k < N; ++k)
			{
				const double Cc = Ra + Len * (k + 0.5) / N;
				if (Cc - Ww * 0.5 < Ra + 40.0 || Cc + Ww * 0.5 > Rb - 40.0) { continue; }
				if (W.bHasDoor && FMath::Abs(Cc - W.DoorAt) < W.DoorWidth * 0.5 + Ww * 0.5 + 40.0) { continue; }
				W.Windows.Add(FVector4(Cc, Ww, Sill, Head));
			}
		}
	}

	for (const FWallSeg& W : Walls)
	{
		FRammsPieceDesc P;
		P.Kind = ERammsProcPieceKind::Wall;
		P.SizeX = W.B - W.A; P.SizeY = T; P.SizeZ = H;
		P.MaterialPath = MatWall; P.MaterialPath2 = MatTrimIn; P.MaterialPath3 = MatGlass;
		P.OpeningWidth = W.bHasDoor ? W.DoorWidth + 2.0 : 0.0;
		P.OpeningOffset = W.bHasDoor ? W.DoorAt - W.A : 0.0;
		P.OpeningHeight = 210.0;
		for (const FVector4& Wn : W.Windows) { P.Openings += FString::Printf(TEXT("%.1f,%.1f,%.1f,%.1f;"), Wn.X - W.A, Wn.Y, Wn.Z, Wn.W); }
		P.Transform = W.bAlongX ? FTransform(FRotator(0.0, 0.0, 0.0), FVector(W.A, W.Line, Z0)) : FTransform(FRotator(0.0, 90.0, 0.0), FVector(W.Line, W.A, Z0));
		P.Seed = NextSeed();
		RammsPCG::WritePiece(Pieces, P);

		if (W.bHasDoor)
		{
			const double Thresh = Rng.FRand() < PThreshold ? RammsPCG::RandRange(Rng, 2.0, 6.0) : 0.0;
			const bool bNarrow = W.DoorWidth < S->DoorClearWidth;
			const bool bHigh = Thresh > S->DoorThresholdMax;
			// Leaf swung open 90 degrees into room A, hinged at the opening's start.
			const FVector Hinge = W.bAlongX ? FVector(W.DoorAt - W.DoorWidth * 0.5, W.Line, Z0) : FVector(W.Line, W.DoorAt - W.DoorWidth * 0.5, Z0);
			const FVector2D ACentre = W.RoomA >= 0 ? Rooms[W.RoomA].Rect.GetCenter() : FVector2D(Site.GetCenter());
			const double IntoA = W.bAlongX ? (ACentre.Y > W.Line ? 1.0 : -1.0) : (ACentre.X > W.Line ? 1.0 : -1.0);
			const double WallYaw = W.bAlongX ? 0.0 : 90.0;
			const FName DoorKind = W.RoomB < 0 ? FName(TEXT("Entrance")) : FName(TEXT("Door"));
			const ERammsComplianceIssue DoorIssue = bNarrow ? ERammsComplianceIssue::DoorTooNarrow : (bHigh ? ERammsComplianceIssue::ThresholdTooHigh : ERammsComplianceIssue::None);
			const FName DoorSub = bNarrow ? FName(TEXT("Narrow")) : (bHigh ? FName(TEXT("RaisedThreshold")) : FName(TEXT("Standard")));
			const double DoorMeasure = bHigh && !bNarrow ? Thresh : W.DoorWidth;
			const double DoorLimit = bHigh && !bNarrow ? S->DoorThresholdMax : S->DoorClearWidth;
			// A real door leaf from the palette (handle included), scaled to the opening and standing open
			// against the casing; the procedural leaf is the fallback.
			FRammsPaletteMesh Leaf;
			const FName LeafSlot = W.RoomB < 0 ? RammsPaletteSlots::DoorExterior : RammsPaletteSlots::DoorInterior;
			const bool bLeaf = Palette && (Palette->PickMesh(LeafSlot, Rng, Leaf) || Palette->PickMesh(RammsPaletteSlots::DoorInterior, Rng, Leaf)) && Leaf.Footprint.Y > 30.0 && Leaf.Height > 100.0;
			if (bLeaf)
			{
				const FVector U = W.bAlongX ? FVector(1, 0, 0) : FVector(0, 1, 0);
				const FVector V = W.bAlongX ? FVector(0, IntoA, 0) : FVector(IntoA, 0, 0); // +Y of the leaf's facing frame = into room A
				const double LeafW = W.DoorWidth - 1.0;
				const double Thick = FMath::Clamp(Leaf.Footprint.X, 3.0, 25.0);
				const double Sy = LeafW / FMath::Max(Leaf.Footprint.Y, 1.0), Sz = 203.0 / FMath::Max(Leaf.Height, 1.0);
				// Facing-frame +Y = (-sin yaw, cos yaw) must point along V.
				double LeafYaw = FMath::RadiansToDegrees(FMath::Atan2(-V.X, V.Y));
				if (Leaf.HandleSide < 0.0) { LeafYaw += 180.0; } // handle on the free edge, away from the hinge
				const FVector Centre = Hinge + U * (Thick * 0.5 + 1.0) + V * (T * 0.5 + 2.5 + LeafW * 0.5) + FVector(0, 0, Thresh);
				const FRotator YawRot(0.0, LeafYaw, 0.0);
				const FRotator Rot = (YawRot.Quaternion() * Leaf.RotationOffset.Quaternion()).Rotator();
				const bool bSwap = FMath::Abs(FMath::Abs(FMath::Fmod(Leaf.RotationOffset.Yaw, 180.0)) - 90.0) < 1.0;
				const FVector S3 = (bSwap ? FVector(Sy, 1.0, Sz) : FVector(1.0, Sy, Sz)) * Leaf.Scale;
				const FVector Loc = Centre + YawRot.RotateVector(FVector(Leaf.LocationOffset.X, Leaf.LocationOffset.Y * Sy, Leaf.LocationOffset.Z * Sz));
				const int32 d = Props.Add(FTransform(Rot, Loc, S3), FVector(-Thick * 0.5, -LeafW * 0.5, 0.0), FVector(Thick * 0.5, LeafW * 0.5, 203.0), NextSeed());
				Props.SetPath(d, RammsPCG::Mesh, Leaf.Mesh.ToSoftObjectPath());
				RammsPCG::WriteManifest(Props, d, DoorKind, DoorSub, !bNarrow && !bHigh, DoorIssue, DoorMeasure, DoorLimit);
			}
			else
			{
				FRammsPieceDesc D;
				D.Kind = ERammsProcPieceKind::Door;
				D.SizeX = W.DoorWidth; D.SizeY = 4.0; D.SizeZ = 205.0; D.Rise = 0.0;
				D.MaterialPath = MatDoor; D.MaterialPath2 = MatMetal;
				D.ManifestKind = DoorKind;
				D.Measure = DoorMeasure; D.Threshold = DoorLimit;
				D.bCompliant = !bNarrow && !bHigh;
				D.Issue = DoorIssue;
				D.ManifestSubtype = DoorSub;
				// Swung open against the casing on room A's side, clear of the jamb.
				const FVector U = W.bAlongX ? FVector(1, 0, 0) : FVector(0, 1, 0);
				const FVector V = W.bAlongX ? FVector(0, IntoA, 0) : FVector(IntoA, 0, 0);
				// The procedural leaf extends along its +X: point that into room A.
				D.Transform = FTransform(FRotator(0.0, FMath::RadiansToDegrees(FMath::Atan2(V.Y, V.X)), 0.0), Hinge + U * 3.0 + V * (T * 0.5 + 2.5));
				D.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, D);
			}
			if (Thresh > 0.1)
			{
				FRammsPieceDesc Th;
				Th.Kind = ERammsProcPieceKind::Slab;
				Th.SizeX = W.DoorWidth + 2.0; Th.SizeY = T + 6.0; Th.SizeZ = Thresh + 10.0;
				Th.MaterialPath = MatMetal;
				Th.ManifestKind = FName(TEXT("Threshold"));
				Th.ManifestSubtype = bHigh ? FName(TEXT("High")) : FName(TEXT("Low"));
				Th.Measure = Thresh; Th.Threshold = S->DoorThresholdMax; Th.bCompliant = !bHigh; Th.Issue = bHigh ? ERammsComplianceIssue::ThresholdTooHigh : ERammsComplianceIssue::None;
				Th.Transform = FTransform(FRotator(0.0, WallYaw, 0.0), Hinge + FVector(0, 0, Thresh));
				Th.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, Th);
			}
		}
	}

	// Wall finishes: a 1 cm liner in the room's paint / wallpaper (tile below 120 cm in bathrooms and some
	// kitchens) on each inner face, cut around door and window openings, with a skirting board. Shared walls
	// get a different finish on each side this way.
	auto EmitLiners = [&](const FRoom& R)
	{
		struct FCut { double A, B, Lo, Hi; };
		for (int32 Side = 0; Side < 4; ++Side)
		{
			const bool bAlongX = Side < 2;                     // 0: min Y, 1: max Y, 2: min X, 3: max X
			const double Edge = Side == 0 ? R.Rect.Min.Y : Side == 1 ? R.Rect.Max.Y : Side == 2 ? R.Rect.Min.X : R.Rect.Max.X;
			const double SiteEdge = Side == 0 ? Site.Min.Y : Side == 1 ? Site.Max.Y : Side == 2 ? Site.Min.X : Site.Max.X;
			const bool bExt = FMath::IsNearlyEqual(Edge, SiteEdge, Tol);
			const double Inward = (Side == 0 || Side == 2) ? 1.0 : -1.0;
			const double Face = Edge + Inward * (bExt ? 0.0 : T * 0.5);
			auto EndInset = [&](double V, double SiteV) { return FMath::IsNearlyEqual(V, SiteV, Tol) ? 0.0 : T * 0.5; };
			const double A0 = (bAlongX ? R.Rect.Min.X : R.Rect.Min.Y) + EndInset(bAlongX ? R.Rect.Min.X : R.Rect.Min.Y, bAlongX ? Site.Min.X : Site.Min.Y);
			const double B0 = (bAlongX ? R.Rect.Max.X : R.Rect.Max.Y) - EndInset(bAlongX ? R.Rect.Max.X : R.Rect.Max.Y, bAlongX ? Site.Max.X : Site.Max.Y);
			if (B0 - A0 < 5.0) { continue; }
			TArray<FCut> Cuts;
			for (int32 d = 0; d < R.DoorCentres.Num(); ++d)
			{
				const FVector2D& Dc = R.DoorCentres[d];
				const double Across = bAlongX ? Dc.Y : Dc.X, Along = bAlongX ? Dc.X : Dc.Y;
				if (FMath::Abs(Across - Edge) > T) { continue; }
				const double Hw = (R.DoorWidths.IsValidIndex(d) ? R.DoorWidths[d] : 90.0) * 0.5 + 1.0;
				Cuts.Add({ Along - Hw, Along + Hw, 0.0, 210.0 });
			}
			if (bExt)
			{
				for (const FWallSeg& W : Walls)
				{
					if (W.RoomB >= 0 || W.bAlongX != bAlongX || FMath::Abs(W.Line - (Edge - Inward * T * 0.5)) > 2.0) { continue; }
					for (const FVector4& Wn : W.Windows) { Cuts.Add({ Wn.X - Wn.Y * 0.5, Wn.X + Wn.Y * 0.5, Wn.Z, Wn.W }); }
				}
			}
			Cuts.Sort([](const FCut& X1, const FCut& X2) { return X1.A < X2.A; });
			auto Strip = [&](double A, double B, double Lo, double Hi, double Thick, const FString& Mat)
			{
				if (B - A < 0.5 || Hi - Lo < 0.5) { return; }
				const double Mid = (A + B) * 0.5, Off = Face + Inward * Thick * 0.5;
				const FVector Cen = bAlongX ? FVector(Mid, Off, Z0 + (Lo + Hi) * 0.5) : FVector(Off, Mid, Z0 + (Lo + Hi) * 0.5);
				RammsPCG::WriteCube(Primitives, Cen, bAlongX ? FVector(B - A, Thick, Hi - Lo) : FVector(Thick, B - A, Hi - Lo), 0.0, Mat, NextSeed());
			};
			const double Split = R.WallMatLow.IsEmpty() ? 0.0 : 120.0;
			auto Finish = [&](double A, double B, double Lo, double Hi)
			{
				if (Split > Lo && Split < Hi) { Strip(A, B, Lo, Split, 1.0, R.WallMatLow); Strip(A, B, Split, Hi, 1.0, R.WallMat); }
				else { Strip(A, B, Lo, Hi, 1.0, Hi <= Split ? R.WallMatLow : R.WallMat); }
			};
			double Xc = A0;
			for (const FCut& Ct : Cuts)
			{
				const double Ca = FMath::Clamp(Ct.A, A0, B0), Cb = FMath::Clamp(Ct.B, A0, B0);
				if (Cb <= Ca) { continue; }
				Finish(Xc, Ca, 0.0, H);
				Finish(Ca, Cb, 0.0, Ct.Lo);
				Finish(Ca, Cb, Ct.Hi, H);
				if (Ct.Lo < 1.0) { Strip(Xc, Ca, 0.0, 10.0, 1.6, MatTrimIn); } else { Strip(Xc, Cb, 0.0, 10.0, 1.6, MatTrimIn); }
				Xc = Cb;
			}
			Finish(Xc, B0, 0.0, H);
			Strip(Xc, B0, 0.0, 10.0, 1.6, MatTrimIn);
		}
	};

	// Floors, routes, furniture per room.
	const double Intrude = S->NonCompliance <= 0.0 ? 0.0 : FMath::Clamp(S->HazardIntrusionChance * (0.5 + 2.0 * S->NonCompliance), 0.0, 1.0);
	for (const FRoom& R : Rooms)
	{
		const FVector2D Ctr = R.Rect.GetCenter();
		const FVector2D Sz = R.Rect.GetSize();
		// Floors meet under the wall centre lines (no overlap, so no z-fighting in door openings).
		RammsPCG::WriteCube(Primitives, FVector(Ctr.X, Ctr.Y, Z0 - 10.0), FVector(Sz.X, Sz.Y, 20.0), 0.0, R.FloorMat.IsEmpty() ? MatWood : R.FloorMat, NextSeed());
		EmitLiners(R);
		{
			const int32 f = Features.AddBox(FVector(Ctr.X, Ctr.Y, Z0), 0.0, FVector(Sz.X, Sz.Y, H), NextSeed());
			RammsPCG::WriteManifest(Features, f, FName(TEXT("Room")), R.Kind, true, ERammsComplianceIssue::None, FMath::Min(Sz.X, Sz.Y), S->PreferredClearWidth);
			Features.SetInt(f, RammsPCG::RoomId, R.Id);
		}

		// Route segments: each door to the room centre.
		struct FRouteSeg { FVector2D A, B; double MinClear; };
		TArray<FRouteSeg> RoomRoutes;
		for (const FVector2D& Dc : R.DoorCentres) { RoomRoutes.Add({ Dc, Ctr, FMath::Min(Sz.X, Sz.Y) }); }
		if (R.DoorCentres.Num() == 0) { RoomRoutes.Add({ FVector2D(R.Rect.Min.X + 60.0, Ctr.Y), Ctr, Sz.Y }); }

		// --- furniture -----------------------------------------------------------------------------
		// Everything is a footprint box (depth along the mesh's facing, width across it; the palette
		// stores footprints in that frame) that must lie inside the room's inner rectangle, overlap
		// nothing placed before it, and stay out of door swings. Pieces are placed as the groups a
		// person would arrange them in: a sofa with its coffee table, a bed with its night tables,
		// chairs around a table, a desk with its chair.
		const FBox2D Inner(R.Rect.Min + FVector2D(T * 0.5 + 2.0, T * 0.5 + 2.0), R.Rect.Max - FVector2D(T * 0.5 + 2.0, T * 0.5 + 2.0));
		TArray<FBox2D> Placed;
		auto InsideInner = [&](const FBox2D& B) { return B.Min.X >= Inner.Min.X && B.Min.Y >= Inner.Min.Y && B.Max.X <= Inner.Max.X && B.Max.Y <= Inner.Max.Y; };
		auto Fits = [&](const FBox2D& B, double Gap) -> bool
		{
			if (!InsideInner(B)) { return false; }
			const FBox2D G = B.ExpandBy(Gap);
			for (const FBox2D& P : Placed) { if (P.Intersect(G)) { return false; } }
			for (const FBox2D& K : R.Keepouts) { if (K.Intersect(B)) { return false; } }
			return true;
		};
		auto DistPointBox = [](const FVector2D& P, const FBox2D& B) { const FVector2D D(FMath::Max(FMath::Max(B.Min.X - P.X, 0.0), P.X - B.Max.X), FMath::Max(FMath::Max(B.Min.Y - P.Y, 0.0), P.Y - B.Max.Y)); return D.Size(); };
		auto DistSegBox = [&](const FVector2D& A, const FVector2D& Bp, const FBox2D& Box)
		{
			double Best = TNumericLimits<double>::Max();
			for (int32 k = 0; k <= 24; ++k) { Best = FMath::Min(Best, DistPointBox(A + (Bp - A) * (k / 24.0), Box)); }
			return Best;
		};
		auto RouteClearance = [&](const FBox2D& B) -> double
		{
			// The aisle left around each door-to-centre line once B is in place: the nearest obstacle
			// (or wall) on either side of the line, measured where B comes closest, summed.
			double Worst = TNumericLimits<double>::Max();
			for (const FRouteSeg& Rs : RoomRoutes)
			{
				const FVector2D AB = Rs.B - Rs.A;
				const double L2 = FMath::Max(AB.SizeSquared(), 1e-6);
				const double t = FMath::Clamp(FVector2D::DotProduct(B.GetCenter() - Rs.A, AB) / L2, 0.0, 1.0);
				const FVector2D Cp = Rs.A + AB * t;
				const FVector2D Dir = AB.GetSafeNormal();
				const FVector2D N(-Dir.Y, Dir.X);
				double Near[2] = { 0.0, 0.0 };
				for (int32 k = 0; k < 2; ++k)
				{
					const FVector2D Nk = N * (k == 0 ? 1.0 : -1.0);
					// Distance from the line to the room boundary on this side.
					double Wall = TNumericLimits<double>::Max();
					if (FMath::Abs(Nk.X) > 1e-6) { Wall = FMath::Min(Wall, (Nk.X > 0 ? Inner.Max.X - Cp.X : Cp.X - Inner.Min.X) / FMath::Abs(Nk.X)); }
					if (FMath::Abs(Nk.Y) > 1e-6) { Wall = FMath::Min(Wall, (Nk.Y > 0 ? Inner.Max.Y - Cp.Y : Cp.Y - Inner.Min.Y) / FMath::Abs(Nk.Y)); }
					Near[k] = FMath::Max(Wall, 0.0);
					auto Consider = [&](const FBox2D& P)
					{
						if (FVector2D::DotProduct(P.GetCenter() - Cp, Nk) < 0.0) { return; } // other side
						Near[k] = FMath::Min(Near[k], DistSegBox(Rs.A, Rs.B, P));
					};
					Consider(B);
					for (const FBox2D& P : Placed) { Consider(P); }
				}
				Worst = FMath::Min(Worst, Near[0] + Near[1]);
			}
			return Worst;
		};
		auto BoxFor = [](const FVector2D& P, double Yaw, double fx, double fy)
		{
			// Axis-aligned bounds of the footprint rotated by Yaw (exact for any angle, not just 90s).
			const double r = FMath::DegreesToRadians(Yaw), c = FMath::Abs(FMath::Cos(r)), sn = FMath::Abs(FMath::Sin(r));
			const FVector2D Half((fx * c + fy * sn) * 0.5, (fx * sn + fy * c) * 0.5);
			return FBox2D(P - Half, P + Half);
		};
		auto Facing = [](double Yaw) { const double r = FMath::DegreesToRadians(Yaw); return FVector2D(FMath::Cos(r), FMath::Sin(r)); };
		auto Side = [](double Yaw) { const double r = FMath::DegreesToRadians(Yaw); return FVector2D(-FMath::Sin(r), FMath::Cos(r)); };
		auto WallYaw = [](int32 w) { return w == 0 ? 90.0 : w == 1 ? 180.0 : w == 2 ? -90.0 : 0.0; };
		auto WallRange = [&](int32 w, double& Lo, double& Hi) { if (w == 0 || w == 2) { Lo = Inner.Min.X; Hi = Inner.Max.X; } else { Lo = Inner.Min.Y; Hi = Inner.Max.Y; } };
		auto WallPos = [&](int32 w, double Along, double Depth) -> FVector2D
		{
			switch (w)
			{
			case 0:  return FVector2D(Along, Inner.Min.Y + Depth * 0.5 + 1.0);
			case 1:  return FVector2D(Inner.Max.X - Depth * 0.5 - 1.0, Along);
			case 2:  return FVector2D(Along, Inner.Max.Y - Depth * 0.5 - 1.0);
			default: return FVector2D(Inner.Min.X + Depth * 0.5 + 1.0, Along);
			}
		};

		struct FItem { FName Slot; FRammsPaletteMesh M; FVector2D P; double Yaw = 0.0; FBox2D Box; double Z = 0.0; };
		auto Pick = [&](FName Slot, FRammsPaletteMesh& Out) { return Palette && Palette->PickMesh(Slot, Rng, Out); };
		auto Dims = [](const FRammsPaletteMesh& M, double& fx, double& fy) { fx = FMath::Max(M.Footprint.X, 15.0); fy = FMath::Max(M.Footprint.Y, 15.0); };
		// Place an item at P with the given yaw if it fits; records it and returns true.
		auto TryAt = [&](FName Slot, const FRammsPaletteMesh& M, const FVector2D& P, double Yaw, double Gap, FItem& Out) -> bool
		{
			double fx, fy; Dims(M, fx, fy);
			const FBox2D B = BoxFor(P, Yaw, fx, fy);
			if (!Fits(B, Gap)) { return false; }
			Out.Slot = Slot; Out.M = M; Out.P = P; Out.Yaw = Yaw; Out.Box = B; Out.Z = Z0;
			Placed.Add(B);
			return true;
		};
		// Back against wall w (random when -1), facing into the room. bLongAlongWall turns the piece so its
		// long side hugs the wall (bathtubs, counters).
		auto TryWall = [&](FName Slot, int32 w, bool bLongAlongWall, double Gap, FItem& Out, double AlongHint = -1e9) -> bool
		{
			FRammsPaletteMesh M; if (!Pick(Slot, M)) { return false; }
			double fx, fy; Dims(M, fx, fy);
			for (int32 Try = 0; Try < 14; ++Try)
			{
				const int32 Wall = w >= 0 ? w : Rng.RandRange(0, 3);
				double Yaw = WallYaw(Wall), Depth = fx, Width = fy;
				if (bLongAlongWall && fx > fy) { Yaw += 90.0; Depth = fy; Width = fx; }
				double Lo, Hi; WallRange(Wall, Lo, Hi);
				if (Hi - Lo < Width + 4.0) { if (w >= 0) { return false; } continue; }
				const double Along = (AlongHint > -1e8 && Try < 4) ? FMath::Clamp(AlongHint + RammsPCG::RandRange(Rng, -40.0, 40.0), Lo + Width * 0.5 + 2.0, Hi - Width * 0.5 - 2.0)
					: RammsPCG::RandRange(Rng, Lo + Width * 0.5 + 2.0, Hi - Width * 0.5 - 2.0);
				if (TryAt(Slot, M, WallPos(Wall, Along, Depth), Yaw, Gap, Out)) { return true; }
			}
			return false;
		};
		// A piece at a fixed offset from another (in front of, beside): tries the offset, then nudges.
		auto TryRel = [&](FName Slot, const FItem& Anchor, const FVector2D& Offset, double Yaw, double Gap, FItem& Out) -> bool
		{
			FRammsPaletteMesh M; if (!Pick(Slot, M)) { return false; }
			static const double Nudges[5] = { 0.0, 12.0, -12.0, 24.0, -24.0 };
			for (double N : Nudges)
			{
				if (TryAt(Slot, M, Anchor.P + Offset + Facing(Anchor.Yaw) * N, Yaw, Gap, Out)) { return true; }
			}
			return false;
		};
		// Everything emitted at floor level is an obstacle for the routing pass below, which decides
		// compliance; here the item is written as plain furniture with its line clearance for the record.
		struct FEmitted { int32 Point; FBox2D Box; bool bFloor; bool bIntruder; };
		TArray<FEmitted> Emitted;
		auto Emit = [&](const FItem& It, FName KindOverride = NAME_None)
		{
			const double Clear = RouteClearance(It.Box);
			const int32 p = RammsPCG::WritePickedMesh(Props, It.M, FVector(It.P.X, It.P.Y, It.Z), It.Yaw, NextSeed());
			if (p < 0) { return; }
			const bool bIntruder = KindOverride == FName(TEXT("Hazard"));
			RammsPCG::WriteManifest(Props, p, !KindOverride.IsNone() ? KindOverride : FName(TEXT("Furniture")), It.Slot, true, ERammsComplianceIssue::None, FMath::Max(Clear, 0.0), S->MinClearWidth);
			Props.SetInt(p, RammsPCG::RoomId, R.Id);
			Emitted.Add({ p, It.Box, It.Z <= Z0 + 1.0, bIntruder });
		};
		auto Stack = [&](FName Slot, const FItem& Base, FItem& Out) -> bool
		{
			// Something on top of something (a TV on its stand, a lamp on a night table): no floor test.
			FRammsPaletteMesh M; if (!Pick(Slot, M)) { return false; }
			double fx, fy; Dims(M, fx, fy);
			double bx, by; Dims(Base.M, bx, by);
			if (fx > bx + 10.0 || fy > by + 10.0) { return false; }
			Out.Slot = Slot; Out.M = M; Out.P = Base.P; Out.Yaw = Base.Yaw; Out.Box = BoxFor(Base.P, Base.Yaw, fx, fy); Out.Z = Z0 + Base.M.Height + 1.0;
			return true;
		};
		auto ChairsAround = [&](const FItem& Table, int32 MaxPerSide)
		{
			double tx, ty; Dims(Table.M, tx, ty);
			FRammsPaletteMesh M; if (!Pick(RammsPaletteSlots::FurnitureChair, M)) { return; }
			double cx, cy; Dims(M, cx, cy);
			const FVector2D F = Facing(Table.Yaw), Sd = Side(Table.Yaw);
			// Along both long sides (the table's facing axis, length tx): chairs face the table.
			const int32 PerSide = FMath::Clamp(static_cast<int32>(tx / (cy + 15.0)), 1, MaxPerSide);
			for (int32 sgn = -1; sgn <= 1; sgn += 2)
			{
				for (int32 i = 0; i < PerSide; ++i)
				{
					const double a = (i - (PerSide - 1) * 0.5) * (tx / PerSide);
					const FVector2D P = Table.P + F * a + Sd * sgn * (ty * 0.5 + cx * 0.5 + 6.0);
					const double Yaw = Table.Yaw + (sgn > 0 ? -90.0 : 90.0);
					FItem It; if (TryAt(RammsPaletteSlots::FurnitureChair, M, P, Yaw, 3.0, It)) { Emit(It); }
				}
			}
			// One at each end when the table is wide enough.
			if (ty > 110.0)
			{
				for (int32 sgn = -1; sgn <= 1; sgn += 2)
				{
					const FVector2D P = Table.P + F * sgn * (tx * 0.5 + cx * 0.5 + 6.0);
					FItem It; if (TryAt(RammsPaletteSlots::FurnitureChair, M, P, Table.Yaw + (sgn > 0 ? 180.0 : 0.0), 3.0, It)) { Emit(It); }
				}
			}
		};
		auto Corner = [&](FName Slot)
		{
			FRammsPaletteMesh M; if (!Pick(Slot, M)) { return; }
			double fx, fy; Dims(M, fx, fy);
			const double m = FMath::Max(fx, fy) * 0.5 + 6.0;
			const FVector2D Corners[4] = { Inner.Min + FVector2D(m, m), FVector2D(Inner.Max.X - m, Inner.Min.Y + m), Inner.Max - FVector2D(m, m), FVector2D(Inner.Min.X + m, Inner.Max.Y - m) };
			const int32 Start = Rng.RandRange(0, 3);
			for (int32 k = 0; k < 4; ++k)
			{
				FItem It; if (TryAt(Slot, M, Corners[(Start + k) % 4], Rng.RandRange(0, 3) * 90.0, 4.0, It)) { Emit(It); return; }
			}
		};
		auto WallItem = [&](FName Slot, double CentreZ)
		{
			FRammsPaletteMesh M; if (!Pick(Slot, M)) { return; }
			double fx, fy; Dims(M, fx, fy);
			for (int32 Try = 0; Try < 6; ++Try)
			{
				const int32 Wall = Rng.RandRange(0, 3);
				double Yaw = WallYaw(Wall), Depth = fx, Width = fy;
				if (fx > fy) { Yaw += 90.0; Depth = fy; Width = fx; }
				double Lo, Hi; WallRange(Wall, Lo, Hi);
				if (Hi - Lo < Width + 40.0) { continue; }
				const FVector2D P = WallPos(Wall, RammsPCG::RandRange(Rng, Lo + Width * 0.5 + 20.0, Hi - Width * 0.5 - 20.0), Depth);
				const FBox2D B = BoxFor(P, Yaw, fx, fy).ExpandBy(10.0);
				bool bClear = InsideInner(B);
				for (const FBox2D& K : R.Keepouts) { if (K.Intersect(B)) { bClear = false; } }
				if (!bClear) { continue; }
				FItem It; It.Slot = Slot; It.M = M; It.P = P; It.Yaw = Yaw; It.Box = B; It.Z = Z0 + CentreZ - M.Height * 0.5;
				Emit(It, FName(TEXT("Decor")));
				return;
			}
		};
		auto Picture = [&]() { WallItem(RammsPaletteSlots::FurniturePicture, 150.0); };

		const double AreaM2 = Sz.X * Sz.Y / 10000.0;
		const double Density = FMath::Clamp(S->FurnitureDensity, 0.0, 1.0);
		const int32 LongWall = Sz.X >= Sz.Y ? (Rng.FRand() < 0.5 ? 0 : 2) : (Rng.FRand() < 0.5 ? 1 : 3);
		const bool bFurnish = Density > 0.0 && (Density >= 0.4 || Rng.FRand() < 0.5 + Density); // every room furnished unless the density is very low
		if (!R.bCorridor && bFurnish)
		{
			FItem A, B, Cc;
			if (R.Kind == FName(TEXT("Living")))
			{
				if (TryWall(RammsPaletteSlots::FurnitureSofa, LongWall, false, 8.0, A))
				{
					Emit(A);
					double ax, ay; Dims(A.M, ax, ay);
					FRammsPaletteMesh Ct; double cx = 0, cy = 0; if (Pick(RammsPaletteSlots::FurnitureCoffeeTable, Ct)) { Dims(Ct, cx, cy); }
					if (TryRel(RammsPaletteSlots::FurnitureCoffeeTable, A, Facing(A.Yaw) * (ax * 0.5 + cx * 0.5 + 45.0), A.Yaw, 6.0, B))
					{
						Emit(B);
						double bx, by; Dims(B.M, bx, by);
						FRammsPaletteMesh Ac; double acx = 0, acy = 0; if (Pick(RammsPaletteSlots::FurnitureArmchair, Ac)) { Dims(Ac, acx, acy); }
						const double sgn = Rng.FRand() < 0.5 ? 1.0 : -1.0;
						const FVector2D Sd = Side(A.Yaw) * sgn;
						const double YawIn = FMath::RadiansToDegrees(FMath::Atan2(-Sd.Y, -Sd.X));
						if (TryRel(RammsPaletteSlots::FurnitureArmchair, B, Sd * (by * 0.5 + acx * 0.5 + 35.0), YawIn, 6.0, Cc)) { Emit(Cc); }
					}
					// A plant beside the sofa, against the same wall.
					FItem L; double lx = 0, ly = 0; FRammsPaletteMesh Lm; if (Pick(RammsPaletteSlots::FurniturePlant, Lm)) { Dims(Lm, lx, ly); }
					if (TryRel(RammsPaletteSlots::FurniturePlant, A, Side(A.Yaw) * (ay * 0.5 + ly * 0.5 + 8.0) + Facing(A.Yaw) * ((lx - ax) * 0.5), A.Yaw, 4.0, L)) { Emit(L); }
					// TV stand on the opposite wall, TV on it.
					FItem St; const double Along = (A.Yaw == 90.0 || A.Yaw == -90.0) ? A.P.X : A.P.Y;
					if (TryWall(RammsPaletteSlots::FurnitureTVStand, (LongWall + 2) % 4, false, 8.0, St, Along))
					{
						Emit(St);
						FItem Tv; if (Stack(RammsPaletteSlots::FurnitureTV, St, Tv)) { Emit(Tv, FName(TEXT("Decor"))); }
					}
				}
				if (AreaM2 > 16.0 && Rng.FRand() < 0.6 && TryWall(RammsPaletteSlots::FurnitureCupboard, -1, false, 8.0, B)) { Emit(B); }
				// A fireplace or a bookshelf on one of the remaining walls.
				{
					FItem Fp;
					if (Rng.FRand() < 0.5 ? TryWall(RammsPaletteSlots::FurnitureFireplace, -1, false, 10.0, Fp) : TryWall(RammsPaletteSlots::FurnitureBookshelf, -1, false, 8.0, Fp)) { Emit(Fp); }
				}
				if (Rng.FRand() < 0.5) { FItem Fl; if (TryWall(RammsPaletteSlots::FurnitureFloorLamp, -1, false, 6.0, Fl)) { Emit(Fl); } }
				Corner(RammsPaletteSlots::FurniturePlant);
				Picture();
			}
			else if (R.Kind == FName(TEXT("Bedroom")))
			{
				if (TryWall(RammsPaletteSlots::FurnitureBed, LongWall, false, 8.0, A))
				{
					Emit(A);
					double ax, ay; Dims(A.M, ax, ay);
					FRammsPaletteMesh Bt; double bx = 0, by = 0; if (Pick(RammsPaletteSlots::FurnitureBedTable, Bt)) { Dims(Bt, bx, by); }
					for (int32 sgn = -1; sgn <= 1; sgn += 2)
					{
						FItem Nt;
						const FVector2D Off = Side(A.Yaw) * sgn * (ay * 0.5 + by * 0.5 + 4.0) - Facing(A.Yaw) * (ax * 0.5 - bx * 0.5);
						if (TryRel(RammsPaletteSlots::FurnitureBedTable, A, Off, A.Yaw, 3.0, Nt))
						{
							Emit(Nt);
							FItem Lp; if (Stack(RammsPaletteSlots::FurnitureLamp, Nt, Lp)) { Emit(Lp, FName(TEXT("Decor"))); }
						}
					}
				}
				if (TryWall(RammsPaletteSlots::FurnitureCupboard, -1, false, 8.0, B)) { Emit(B); }
				if (AreaM2 > 14.0 && Rng.FRand() < 0.5 && TryWall(RammsPaletteSlots::FurnitureArmchair, -1, false, 8.0, Cc)) { Emit(Cc); }
				Picture();
			}
			else if (R.Kind == FName(TEXT("Office")))
			{
				// Desks in a row along the long wall, each with its chair on the room side.
				FRammsPaletteMesh Dk; double dx = 0, dy = 0;
				const int32 NumDesks = Pick(RammsPaletteSlots::FurnitureDesk, Dk) ? (Dims(Dk, dx, dy), FMath::Clamp(static_cast<int32>(AreaM2 / 9.0), 1, 4)) : 0;
				double Lo, Hi; WallRange(LongWall, Lo, Hi);
				for (int32 i = 0; i < NumDesks; ++i)
				{
					const double Along = Lo + (Hi - Lo) * (i + 0.5) / NumDesks;
					FItem D;
					if (!TryWall(RammsPaletteSlots::FurnitureDesk, LongWall, false, 10.0, D, Along)) { continue; }
					Emit(D);
					double ddx, ddy; Dims(D.M, ddx, ddy);
					FRammsPaletteMesh Ch; double cx = 0, cy = 0; if (Pick(RammsPaletteSlots::FurnitureOfficeChair, Ch)) { Dims(Ch, cx, cy); }
					FItem C2; if (TryRel(RammsPaletteSlots::FurnitureOfficeChair, D, Facing(D.Yaw) * (ddx * 0.5 + cx * 0.5 + 12.0), D.Yaw + 180.0, 3.0, C2)) { Emit(C2); }
				}
				// Storage opposite the desks (filing cabinets, shelving), then a printer / water cooler in a corner.
				if (TryWall(RammsPaletteSlots::FurnitureOfficeStorage, (LongWall + 2) % 4, false, 8.0, B) || TryWall(RammsPaletteSlots::FurnitureCupboard, (LongWall + 2) % 4, false, 8.0, B)) { Emit(B); }
				if (AreaM2 > 10.0 && Rng.FRand() < 0.7) { Corner(RammsPaletteSlots::FurnitureOfficeProp); }
				if (AreaM2 > 12.0 && Rng.FRand() < 0.5) { Corner(RammsPaletteSlots::FurniturePlant); }
				if (Rng.FRand() < 0.6) { WallItem(RammsPaletteSlots::FurnitureWhiteboard, 150.0); } else { Picture(); }
			}
			else if (R.Kind == FName(TEXT("Dining")) || R.Kind == FName(TEXT("Kitchen")) || R.Kind == FName(TEXT("Meeting")))
			{
				FRammsPaletteMesh Tb;
				if (Pick(RammsPaletteSlots::FurnitureTable, Tb))
				{
					double tx, ty; Dims(Tb, tx, ty);
					// Table in the middle, long side along the room's long axis, leaving the door routes free.
					const double Yaw = (Sz.X >= Sz.Y) == (ty >= tx) ? 0.0 : 90.0;
					for (int32 Try = 0; Try < 8; ++Try)
					{
						const FVector2D P = Ctr + FVector2D(RammsPCG::RandRange(Rng, -Sz.X * 0.15, Sz.X * 0.15), RammsPCG::RandRange(Rng, -Sz.Y * 0.15, Sz.Y * 0.15)) * (Try > 0 ? 1.0 : 0.0);
						if (!TryAt(RammsPaletteSlots::FurnitureTable, Tb, P, Yaw, 60.0, A)) { continue; }
						if (RouteClearance(A.Box) < S->MinClearWidth) { Placed.Pop(); continue; }
						Emit(A); ChairsAround(A, 3);
						break;
					}
				}
				if (R.Kind == FName(TEXT("Kitchen")))
				{
					// A counter run along one wall: low cabinets with a sink and a stove in the row, upper
					// cabinets above them, and a fridge at the end. Falls back to cupboards when the
					// palette has no kitchen pieces.
					double Lo, Hi; WallRange(LongWall, Lo, Hi);
					FRammsPaletteMesh Probe;
					if (Palette && Palette->PickMesh(RammsPaletteSlots::FurnitureKitchenLow, Rng, Probe))
					{
						double Along = Lo + 4.0;
						int32 Placed_ = 0;
						bool bSink = false, bStove = false;
						while (Along < Hi - 60.0 && Placed_ < 8)
						{
							FName Slot = RammsPaletteSlots::FurnitureKitchenLow;
							if (!bSink && Placed_ == 1) { Slot = RammsPaletteSlots::FurnitureKitchenSink; }
							else if (!bStove && Placed_ == 3) { Slot = RammsPaletteSlots::FurnitureKitchenStove; }
							else if (Placed_ == 5 && Rng.FRand() < 0.5) { Slot = RammsPaletteSlots::FurnitureKitchenDishwasher; }
							FRammsPaletteMesh M; if (!Pick(Slot, M)) { Slot = RammsPaletteSlots::FurnitureKitchenLow; if (!Pick(Slot, M)) { break; } }
							double fx, fy; Dims(M, fx, fy);
							if (Along + fy > Hi - 2.0) { break; }
							FItem Cu;
							if (!TryAt(Slot, M, WallPos(LongWall, Along + fy * 0.5, fx), WallYaw(LongWall), 1.0, Cu)) { Along += fy; continue; }
							Emit(Cu);
							if (Slot == RammsPaletteSlots::FurnitureKitchenSink) { bSink = true; }
							if (Slot == RammsPaletteSlots::FurnitureKitchenStove) { bStove = true; }
							// Upper cabinet above, same width class.
							FRammsPaletteMesh Up;
							if (Pick(RammsPaletteSlots::FurnitureKitchenUpper, Up))
							{
								double ux, uy; Dims(Up, ux, uy);
								if (uy <= fy + 5.0)
								{
									FItem U; U.Slot = RammsPaletteSlots::FurnitureKitchenUpper; U.M = Up; U.P = WallPos(LongWall, Along + fy * 0.5, ux); U.Yaw = WallYaw(LongWall);
									U.Box = BoxFor(U.P, U.Yaw, ux, uy); U.Z = Z0 + 145.0;
									Emit(U, FName(TEXT("Decor")));
								}
							}
							Along += fy;
							++Placed_;
						}
						// Fridge / tall cabinet at the end of the run.
						FItem Tall; if (TryWall(RammsPaletteSlots::FurnitureKitchenTall, LongWall, false, 2.0, Tall, Along + 40.0)) { Emit(Tall); }
					}
					else
					{
						const int32 N = FMath::Clamp(static_cast<int32>((Hi - Lo) / 110.0), 1, 4);
						for (int32 i = 0; i < N; ++i)
						{
							FItem Cu; if (TryWall(RammsPaletteSlots::FurnitureCupboard, LongWall, false, 2.0, Cu, Lo + (Hi - Lo) * (i + 0.5) / N)) { Emit(Cu); }
						}
					}
				}
				else if (TryWall(RammsPaletteSlots::FurnitureCupboard, -1, false, 8.0, B)) { Emit(B); }
				Picture();
			}
			else if (R.Kind == FName(TEXT("Shop")))
			{
				// Products on every measured shelf board of a unit, in a row along its front edge. Plain props
				// (no manifest record): they sit inside the unit's footprint, which is already the obstacle.
				auto StockShelf = [&](const FItem& U)
				{
					if (U.M.ShelfHeights.Num() == 0 || !Palette) { return; }
					double ux, uy; Dims(U.M, ux, uy);
					const FVector2D F = Facing(U.Yaw), Sd = Side(U.Yaw);
					for (int32 h = 0; h < U.M.ShelfHeights.Num(); ++h)
					{
						const double Hgt = U.M.ShelfHeights[h];
						if (Hgt > 175.0) { continue; } // nothing on the very top
						// Clearance up to the next board (or the unit's top): products must fit under it.
						const double ShelfClear = (h + 1 < U.M.ShelfHeights.Num() ? U.M.ShelfHeights[h + 1] : U.M.Height) - Hgt - 3.0;
						FRammsPaletteMesh Pr; bool bFits = false;
						for (int32 Try = 0; Try < 6 && !bFits; ++Try)
						{
							if (!Palette->PickMesh(RammsPaletteSlots::StoreProduct, Rng, Pr)) { return; }
							bFits = Pr.Height <= ShelfClear;
						}
						if (!bFits) { continue; }
						double px, py; Dims(Pr, px, py);
						px = FMath::Max(Pr.Footprint.X, 4.0); py = FMath::Max(Pr.Footprint.Y, 4.0);
						if (px > ux * 0.9) { continue; }
						const double Front = ux * 0.5 - px * 0.5 - 3.0;
						const double Step = py + 1.5;
						const int32 N = FMath::Clamp(static_cast<int32>((uy - 8.0) / Step), 0, 40);
						const double Fill = RammsPCG::RandRange(Rng, 0.6, 1.0); // some gaps, like a real shelf
						for (int32 k = 0; k < N; ++k)
						{
							if (Rng.FRand() > Fill) { continue; }
							const double a = -uy * 0.5 + 4.0 + Step * (k + 0.5);
							const FVector2D Pp = U.P + F * Front + Sd * a;
							RammsPCG::WritePickedMesh(Props, Pr, FVector(Pp.X, Pp.Y, U.Z + Hgt + 0.3), U.Yaw, NextSeed());
						}
					}
				};
				// A shop floor laid out like a small supermarket: checkout lanes by the entrance, wall freezers
				// along one long wall, produce tables along the other, a deli counter across the far end, and
				// gondola rows (shelving back to back) between them with aisles. Aisle and checkout-lane widths
				// are drawn per aisle - most at or above the preferred clear width, some (NonCompliance) below
				// the minimum - and each is recorded in the manifest.
				const bool bAlongX = Sz.X >= Sz.Y;
				const int32 FreezerWall = bAlongX ? (Rng.FRand() < 0.5 ? 0 : 2) : (Rng.FRand() < 0.5 ? 1 : 3);
				const int32 FarWall = (FreezerWall + 2) % 4;
				const FVector2D DoorP = R.DoorCentres.Num() > 0 ? R.DoorCentres[0] : Ctr;
				const double DoorWd = R.DoorWidths.Num() > 0 ? R.DoorWidths[0] : 100.0;
				const double Dw[4] = { DoorP.Y - Inner.Min.Y, Inner.Max.X - DoorP.X, Inner.Max.Y - DoorP.Y, DoorP.X - Inner.Min.X };
				int32 DoorWall = 0; for (int32 w = 1; w < 4; ++w) { if (Dw[w] < Dw[DoorWall]) { DoorWall = w; } }
				const double DoorAlong = (DoorWall == 0 || DoorWall == 2) ? DoorP.X : DoorP.Y;
				const bool bWallZ = H >= 290.0; // room for hanging signs
				auto Hang = [&](FName Slot, const FVector2D& P, double Yaw, double Z)
				{
					FRammsPaletteMesh M; if (!Pick(Slot, M)) { return; }
					FItem It; It.Slot = Slot; It.M = M; It.P = P; It.Yaw = Yaw; It.Box = BoxFor(P, Yaw, M.Footprint.X, M.Footprint.Y); It.Z = Z;
					Emit(It, FName(TEXT("Decor")));
				};
				// Checkout lanes: counters standing out from the entrance wall, long side into the room, a lane
				// between each pair, starting beside the door on its roomier side.
				{
					double Lo, Hi; WallRange(DoorWall, Lo, Hi);
					const double Dir = (DoorAlong - Lo) > (Hi - DoorAlong) ? -1.0 : 1.0;
					FRammsPaletteMesh Cm;
					if (Pick(RammsPaletteSlots::StoreCounter, Cm))
					{
						double cx, cy; Dims(Cm, cx, cy);
						const int32 Lanes = FMath::Clamp(static_cast<int32>(((Dir > 0 ? Hi - DoorAlong : DoorAlong - Lo) - DoorWd * 0.5 - 120.0) / (cx + 120.0)), 1, 3);
						double Along = DoorAlong + Dir * (DoorWd * 0.5 + 130.0 + cx * 0.5);
						for (int32 k = 0; k < Lanes; ++k)
						{
							FItem Ck;
							if (!TryAt(RammsPaletteSlots::StoreCounter, Cm, WallPos(DoorWall, Along, cy + 140.0), WallYaw(DoorWall) + 90.0, 2.0, Ck)) { break; }
							Emit(Ck);
							FItem Rg; if (Stack(RammsPaletteSlots::StoreRegister, Ck, Rg)) { Emit(Rg, FName(TEXT("Decor"))); }
							// The lane beside the counter (toward the door side): a manifest record with its width.
							const bool bNarrowLane = Rng.FRand() < S->NonCompliance * 0.5;
							const double LaneW = bNarrowLane ? RammsPCG::RandRange(Rng, 70.0, S->MinClearWidth - 4.0) : RammsPCG::RandRange(Rng, 95.0, 125.0);
							const FVector2D LaneC = WallPos(DoorWall, Along - Dir * (cx * 0.5 + LaneW * 0.5), cy + 140.0);
							const int32 f = Features.AddBox(FVector(LaneC.X, LaneC.Y, Z0), WallYaw(DoorWall) + 90.0, FVector(LaneW, cy, 10.0), NextSeed());
							RammsPCG::WriteManifest(Features, f, FName(TEXT("CheckoutLane")), bNarrowLane ? FName(TEXT("Narrow")) : FName(TEXT("Standard")), !bNarrowLane,
								bNarrowLane ? ERammsComplianceIssue::ClearWidthBelowMinimum : ERammsComplianceIssue::None, LaneW, S->MinClearWidth);
							Features.SetInt(f, RammsPCG::RoomId, R.Id);
							Placed.Add(BoxFor(LaneC, WallYaw(DoorWall) + 90.0, LaneW, cy)); // keep the lane itself clear
							// Impulse rack at the lane's mouth.
							if (Rng.FRand() < 0.6)
							{
								FRammsPaletteMesh Im; if (Pick(RammsPaletteSlots::StoreDisplay, Im))
								{
									double ix, iy; Dims(Im, ix, iy);
									FItem It; if (TryAt(RammsPaletteSlots::StoreDisplay, Im, WallPos(DoorWall, Along, cy * 2.0 + 140.0 + ix * 2.0 + 30.0), WallYaw(DoorWall), 2.0, It)) { Emit(It); }
								}
							}
							Along += Dir * (cx + LaneW);
						}
					}
					// Baskets stacked by the door on the other side.
					FRammsPaletteMesh Bk;
					if (Pick(RammsPaletteSlots::StoreBasket, Bk))
					{
						double bx, by; Dims(Bk, bx, by);
						FItem It;
						if (TryAt(RammsPaletteSlots::StoreBasket, Bk, WallPos(DoorWall, DoorAlong - Dir * (DoorWd * 0.5 + 60.0 + by * 0.5), bx + 30.0), WallYaw(DoorWall), 2.0, It))
						{
							Emit(It);
							for (int32 k = 1; k < 4; ++k) { FItem Up = It; Up.Z = Z0 + k * FMath::Max(Bk.Height * 0.35, 6.0); Emit(Up, FName(TEXT("Decor"))); }
						}
					}
					// Exit sign over the entrance.
					// Exit sign over the street door (not over a door into the next room).
					const bool bStreetDoor = FMath::Abs(DoorP.X - Site.Min.X) < T || FMath::Abs(DoorP.X - Site.Max.X) < T || FMath::Abs(DoorP.Y - Site.Min.Y) < T || FMath::Abs(DoorP.Y - Site.Max.Y) < T;
					if (bWallZ && bStreetDoor) { Hang(RammsPaletteSlots::StoreExitSign, WallPos(DoorWall, DoorAlong, 14.0), WallYaw(DoorWall), Z0 + 228.0); }
				}
				// Wall freezers / fridges along one long wall.
				double FreezerDepth = 0.0;
				{
					double Lo, Hi; WallRange(FreezerWall, Lo, Hi);
					double Along = Lo + 30.0;
					for (int32 n = 0; n < 12 && Along < Hi - 60.0; ++n)
					{
						FRammsPaletteMesh M; if (!Pick(RammsPaletteSlots::StoreFridge, M)) { break; }
						double fx, fy; Dims(M, fx, fy);
						if (Along + fy > Hi - 30.0) { break; }
						FItem Fz;
						if (TryAt(RammsPaletteSlots::StoreFridge, M, WallPos(FreezerWall, Along + fy * 0.5, fx), WallYaw(FreezerWall), 1.0, Fz)) { Emit(Fz); FreezerDepth = FMath::Max(FreezerDepth, fx); }
						Along += fy + 2.0;
					}
				}
				// Produce along the opposite long wall: tables, crates on them, fruit and vegetables in the crates.
				double ProduceDepth = 0.0;
				{
					FRammsPaletteMesh Tm;
					if (Pick(RammsPaletteSlots::StoreProduceTable, Tm))
					{
						double tx, ty; Dims(Tm, tx, ty);
						double Lo, Hi; WallRange(FarWall, Lo, Hi);
						for (double Along = Lo + 200.0 + ty * 0.5; Along + ty * 0.5 < Hi - 200.0; Along += ty + 30.0)
						{
							FItem Tb;
							if (!TryAt(RammsPaletteSlots::StoreProduceTable, Tm, WallPos(FarWall, Along, tx + 10.0), WallYaw(FarWall), 1.0, Tb)) { continue; }
							Emit(Tb);
							ProduceDepth = FMath::Max(ProduceDepth, tx + 10.0);
							const FVector2D F = Facing(Tb.Yaw), Sd = Side(Tb.Yaw);
							const double TopZ = Z0 + Tm.Height;
							FRammsPaletteMesh Cr; const bool bCrates = Pick(RammsPaletteSlots::StoreCrate, Cr);
							double crx = 40.0, cry = 30.0, crz = 0.0;
							if (bCrates) { Dims(Cr, crx, cry); crz = Cr.Height; }
							const int32 Nx = FMath::Max(1, static_cast<int32>((tx - 8.0) / (crx + 3.0))), Ny = FMath::Max(1, static_cast<int32>((ty - 8.0) / (cry + 3.0)));
							for (int32 ix = 0; ix < Nx; ++ix)
							{
								for (int32 iy = 0; iy < Ny; ++iy)
								{
									const FVector2D CrateC = Tb.P + F * ((ix - (Nx - 1) * 0.5) * (crx + 3.0)) + Sd * ((iy - (Ny - 1) * 0.5) * (cry + 3.0));
									if (bCrates) { RammsPCG::WritePickedMesh(Props, Cr, FVector(CrateC.X, CrateC.Y, TopZ + 0.5), Tb.Yaw, NextSeed()); }
									FRammsPaletteMesh Fr; if (!Pick(RammsPaletteSlots::StoreProduce, Fr)) { continue; }
									const double fx = FMath::Max(Fr.Footprint.X, 3.0), fy = FMath::Max(Fr.Footprint.Y, 3.0);
									const int32 Px = FMath::Clamp(static_cast<int32>((crx - 6.0) / (fx + 0.5)), 1, 8), Py = FMath::Clamp(static_cast<int32>((cry - 6.0) / (fy + 0.5)), 1, 8);
									// Two layers, the upper one offset by half an item, mounded a little above the crate rim.
									for (int32 Layer = 0; Layer < 2; ++Layer)
									{
										const double Base = TopZ + 0.5 + (bCrates ? crz * 0.55 : 0.0) + Layer * Fr.Height * 0.7;
										const int32 Lx = Px - Layer, Ly = Py - Layer;
										for (int32 a = 0; a < Lx; ++a)
										{
											for (int32 c = 0; c < Ly; ++c)
											{
												const FVector2D Pp = CrateC + F * ((a - (Lx - 1) * 0.5) * (fx + 0.5)) + Sd * ((c - (Ly - 1) * 0.5) * (fy + 0.5));
												RammsPCG::WritePickedMesh(Props, Fr, FVector(Pp.X, Pp.Y, Base), Tb.Yaw + RammsPCG::RandRange(Rng, -30.0, 30.0), NextSeed());
											}
										}
									}
								}
							}
						}
						if (ProduceDepth > 0.0 && bWallZ)
						{
							double Lo2, Hi2; WallRange(FarWall, Lo2, Hi2);
							Hang(RammsPaletteSlots::StoreSign, WallPos(FarWall, (Lo2 + Hi2) * 0.5, ProduceDepth + 60.0), WallYaw(FarWall), Z0 + 235.0);
						}
					}
				}
				// Deli: glass counter cases across the end wall away from the entrance.
				const int32 EndA = bAlongX ? 3 : 0, EndB = bAlongX ? 1 : 2; // walls at the low / high end of the rows
				const double DistA = FVector2D::Distance(DoorP, WallPos(EndA, (bAlongX ? Inner.Min.Y + Inner.Max.Y : Inner.Min.X + Inner.Max.X) * 0.5, 0.0));
				const double DistB = FVector2D::Distance(DoorP, WallPos(EndB, (bAlongX ? Inner.Min.Y + Inner.Max.Y : Inner.Min.X + Inner.Max.X) * 0.5, 0.0));
				const int32 DeliWall = DistA > DistB ? EndA : EndB;
				double DeliDepth = 0.0;
				{
					double Lo, Hi; WallRange(DeliWall, Lo, Hi);
					// Between the freezers and the produce tables.
					const double Lo2 = Lo + ((FreezerWall == 0 || FreezerWall == 3) ? FreezerDepth : ProduceDepth) + 160.0;
					const double Hi2 = Hi - ((FreezerWall == 0 || FreezerWall == 3) ? ProduceDepth : FreezerDepth) - 160.0;
					double Along = Lo2;
					for (int32 n = 0; n < 5; ++n)
					{
						FRammsPaletteMesh M; if (!Pick(RammsPaletteSlots::StoreDeliCase, M)) { break; }
						double fx, fy; Dims(M, fx, fy);
						if (Along + fy > Hi2) { break; }
						FItem Dc;
						if (TryAt(RammsPaletteSlots::StoreDeliCase, M, WallPos(DeliWall, Along + fy * 0.5, fx + 70.0), WallYaw(DeliWall), 1.0, Dc))
						{
							Emit(Dc);
							DeliDepth = FMath::Max(DeliDepth, fx + 70.0);
							// Goods on the case top.
							FItem Gd; if (Rng.FRand() < 0.7 && Stack(RammsPaletteSlots::StoreDeliItem, Dc, Gd)) { Emit(Gd, FName(TEXT("Decor"))); }
						}
						Along += fy + 1.0;
					}
					if (DeliDepth > 0.0 && bWallZ) { Hang(RammsPaletteSlots::StoreSign, WallPos(DeliWall, (Lo2 + Along) * 0.5, DeliDepth + 50.0), WallYaw(DeliWall), Z0 + 235.0); }
				}
				// Gondola rows across the rest of the floor.
				{
					FRammsPaletteMesh Sh; double sx = 0.0, sy = 0.0;
					if (Pick(RammsPaletteSlots::StoreShelf, Sh))
					{
						Dims(Sh, sx, sy);
						const double RowDepth = sx * 2.0 + 4.0;           // two units back to back
						const double EndGap = 180.0;                         // cross aisles at both ends
						// Short-axis coordinate runs away from the freezer wall.
						const double SMin = bAlongX ? Inner.Min.Y : Inner.Min.X, SMax = bAlongX ? Inner.Max.Y : Inner.Max.X;
						const bool bFromMin = (FreezerWall == 0 || FreezerWall == 3);
						const double LMin = (bAlongX ? Inner.Min.X : Inner.Min.Y) + EndGap + (DeliWall == EndA ? DeliDepth : 0.0);
						const double LMax = (bAlongX ? Inner.Max.X : Inner.Max.Y) - EndGap - (DeliWall == EndB ? DeliDepth : 0.0);
						double Cursor = FreezerDepth + 4.0;
						int32 Aisle = 0;
						while (Aisle < 8)
						{
							const bool bNarrow = Rng.FRand() < S->NonCompliance * 0.6;
							const double AW = bNarrow ? RammsPCG::RandRange(Rng, 66.0, S->MinClearWidth - 4.0)
								: RammsPCG::RandRange(Rng, S->PreferredClearWidth * 0.95, S->PreferredClearWidth * 1.35);
							if (Cursor + AW + RowDepth > (SMax - SMin) - 150.0 - ProduceDepth) { break; } // keep a wide aisle in front of the produce
							// The aisle itself: a manifest record spanning the row length.
							const double sc = bFromMin ? SMin + Cursor + AW * 0.5 : SMax - Cursor - AW * 0.5;
							{
								const double lc = (LMin + LMax) * 0.5;
								const FVector2D AC = bAlongX ? FVector2D(lc, sc) : FVector2D(sc, lc);
								const FVector2D AS = bAlongX ? FVector2D(LMax - LMin, AW) : FVector2D(AW, LMax - LMin);
								const int32 f = Features.AddBox(FVector(AC.X, AC.Y, Z0), 0.0, FVector(AS.X, AS.Y, 10.0), NextSeed());
								RammsPCG::WriteManifest(Features, f, FName(TEXT("Aisle")), bNarrow ? FName(TEXT("Narrow")) : FName(TEXT("Standard")), !bNarrow,
									bNarrow ? ERammsComplianceIssue::ClearWidthBelowMinimum : ERammsComplianceIssue::None, AW, S->MinClearWidth);
								Features.SetInt(f, RammsPCG::RoomId, R.Id);
								// Aisle number sign hanging over the middle of the aisle.
								if (bWallZ) { Hang(RammsPaletteSlots::StoreSign, AC, bAlongX ? 0.0 : 90.0, Z0 + 240.0); }
							}
							Cursor += AW;
							// Row centre line, then the units end to end along it, facing both aisles.
							const double rc = bFromMin ? SMin + Cursor + RowDepth * 0.5 : SMax - Cursor - RowDepth * 0.5;
							for (double l = LMin + sy * 0.5; l + sy * 0.5 <= LMax; l += sy + 1.0)
							{
								for (int32 sgn = -1; sgn <= 1; sgn += 2)
								{
									const double off = sgn * (sx * 0.5 + 2.0);
									const FVector2D P = bAlongX ? FVector2D(l, rc + off) : FVector2D(rc + off, l);
									const double Yaw = bAlongX ? (sgn > 0 ? 90.0 : -90.0) : (sgn > 0 ? 0.0 : 180.0);
									FItem U; if (TryAt(RammsPaletteSlots::StoreShelf, Sh, P, Yaw, 0.5, U)) { Emit(U); StockShelf(U); }
								}
							}
							// End caps: a display at one or both ends of the row, in the cross aisle.
							for (int32 End = 0; End < 2; ++End)
							{
								if (Rng.FRand() > 0.5) { continue; }
								FRammsPaletteMesh Ec; if (!Pick(RammsPaletteSlots::StoreDisplay, Ec)) { break; }
								double ex, ey; Dims(Ec, ex, ey);
								if (ex > 60.0) { continue; } // keep the cross aisle passable
								const double l = End == 0 ? LMin - ex * 0.5 - 3.0 : LMax + ex * 0.5 + 3.0;
								const FVector2D P = bAlongX ? FVector2D(l, rc) : FVector2D(rc, l);
								const double Yaw = bAlongX ? (End == 0 ? 180.0 : 0.0) : (End == 0 ? -90.0 : 90.0);
								FItem It; if (TryAt(RammsPaletteSlots::StoreDisplay, Ec, P, Yaw, 1.0, It)) { Emit(It); }
							}
							Cursor += RowDepth;
							++Aisle;
						}
						// A chest freezer island in the far aisle.
						if (Rng.FRand() < 0.7) { Corner(RammsPaletteSlots::StoreChestFreezer); }
					}
				}
				Corner(RammsPaletteSlots::StoreCart);
				// Back-of-house clutter: boxes, a pallet, a mop bucket in the corners.
				for (int32 k = 0; k < 2; ++k) { Corner(RammsPaletteSlots::StoreClutter); }
			}
			else if (R.Kind == FName(TEXT("Storage")))
			{
				// Stock room: shelving along the walls, boxes.
				for (int32 i = 0; i < 4; ++i) { FItem A2; if (TryWall(RammsPaletteSlots::FurnitureOfficeStorage, -1, true, 4.0, A2)) { Emit(A2); } }
				Corner(RammsPaletteSlots::FurnitureClutter);
			}
			else if (R.Kind == FName(TEXT("Bathroom")))
			{
				if (TryWall(RammsPaletteSlots::FurnitureToilet, -1, false, 10.0, A)) { Emit(A); }
				if (TryWall(RammsPaletteSlots::FurnitureBathtub, -1, true, 6.0, B)) { Emit(B); }
			}
			else
			{
				if (TryWall(RammsPaletteSlots::FurnitureCupboard, -1, false, 8.0, A)) { Emit(A); }
				Corner(RammsPaletteSlots::FurniturePlant);
			}
		}
		else if (R.bCorridor && Density > 0.0 && Rng.FRand() < 0.5)
		{
			// Corridors get a plant or a narrow cabinet on one side, never in the walking line.
			FItem A;
			if (TryWall(Rng.FRand() < 0.6 ? RammsPaletteSlots::FurniturePlant : RammsPaletteSlots::FurnitureCupboard, -1, true, 6.0, A))
			{
				if (RouteClearance(A.Box) >= S->MinClearWidth) { Emit(A); } else { Placed.Pop(); }
			}
		}

		// Deliberate obstacle in the route (NonCompliance): a chair, box or plant pulled into the aisle.
		if (RoomRoutes.Num() > 0 && R.DoorCentres.Num() > 0 && Rng.FRand() < Intrude)
		{
			static const FName Slots[3] = { RammsPaletteSlots::FurnitureChair, RammsPaletteSlots::FurniturePlant, RammsPaletteSlots::FurnitureClutter };
			FName Slot = Slots[Rng.RandRange(0, 2)];
			FRammsPaletteMesh M; if (!Pick(Slot, M)) { Slot = RammsPaletteSlots::FurnitureChair; }
			if (Pick(Slot, M))
			{
				double fx, fy; Dims(M, fx, fy);
				const FRouteSeg& Rs = RoomRoutes[Rng.RandRange(0, RoomRoutes.Num() - 1)];
				const FVector2D Dir = (Rs.B - Rs.A).GetSafeNormal();
				const FVector2D Perp(-Dir.Y, Dir.X);
				const double TargetClear = RammsPCG::RandRange(Rng, 55.0, FMath::Max(56.0, S->MinClearWidth - 3.0));
				for (int32 Try = 0; Try < 6; ++Try)
				{
					const double t = RammsPCG::RandRange(Rng, 0.35, 0.75);
					const double sgn = Rng.FRand() < 0.5 ? 1.0 : -1.0;
					const double Yaw = RammsPCG::RandRange(Rng, 0.0, 360.0);
					const FVector2D P = Rs.A + (Rs.B - Rs.A) * t + Perp * sgn * (TargetClear * 0.5 + FMath::Max(fx, fy) * 0.5);
					FItem It; if (TryAt(Slot, M, P, Yaw, 2.0, It)) { Emit(It, FName(TEXT("Hazard"))); break; }
				}
			}
		}
		// --- routes through the furnished room ---------------------------------------------------
		// A 10 cm occupancy grid of the room with every floor-level footprint blocked; the distance
		// transform gives each free cell its clearance radius, and a widest-path search from each door
		// finds the route that keeps the most room on both sides. Its bottleneck (doubled) is the
		// route's clear width; the pieces pinching it are the ones the manifest reports as obstacles.
		{
			const double Cell = 10.0;
			const int32 NX = FMath::Max(2, FMath::CeilToInt(Inner.GetSize().X / Cell));
			const int32 NY = FMath::Max(2, FMath::CeilToInt(Inner.GetSize().Y / Cell));
			auto CellCentre = [&](int32 ix, int32 iy) { return Inner.Min + FVector2D((ix + 0.5) * Cell, (iy + 0.5) * Cell); };
			auto CellOf = [&](const FVector2D& P, int32& ix, int32& iy)
			{
				ix = FMath::Clamp(FMath::FloorToInt((P.X - Inner.Min.X) / Cell), 0, NX - 1);
				iy = FMath::Clamp(FMath::FloorToInt((P.Y - Inner.Min.Y) / Cell), 0, NY - 1);
			};
			TArray<float> Dist; Dist.Init(1e9f, NX * NY);
			// Sources: blocked cells (inside a footprint) at 0, cells on the border at half a cell (the wall).
			TArray<int32> Queue;
			for (int32 iy = 0; iy < NY; ++iy)
			{
				for (int32 ix = 0; ix < NX; ++ix)
				{
					const int32 id = iy * NX + ix;
					const FVector2D Cc = CellCentre(ix, iy);
					bool bBlocked = false;
					for (const FEmitted& E : Emitted) { if (E.bFloor && E.Box.IsInside(Cc)) { bBlocked = true; break; } }
					if (bBlocked) { Dist[id] = 0.f; Queue.Add(id); }
					else if (ix == 0 || iy == 0 || ix == NX - 1 || iy == NY - 1) { Dist[id] = static_cast<float>(Cell * 0.5); Queue.Add(id); }
				}
			}
			// Distance transform by Dijkstra (8-neighbour); the grid is at most ~100x100.
			{
				TArray<uint8> Done; Done.Init(0, NX * NY);
				while (Queue.Num() > 0)
				{
					int32 Best = 0; for (int32 k = 1; k < Queue.Num(); ++k) { if (Dist[Queue[k]] < Dist[Queue[Best]]) { Best = k; } }
					const int32 u = Queue[Best]; Queue.RemoveAtSwap(Best);
					if (Done[u]) { continue; }
					Done[u] = 1;
					const int32 ux = u % NX, uy = u / NX;
					for (int32 dy = -1; dy <= 1; ++dy) for (int32 dx = -1; dx <= 1; ++dx)
					{
						if (!dx && !dy) { continue; }
						const int32 vx = ux + dx, vy = uy + dy;
						if (vx < 0 || vy < 0 || vx >= NX || vy >= NY) { continue; }
						const int32 v = vy * NX + vx;
						const float nd = Dist[u] + static_cast<float>(Cell * ((dx && dy) ? 1.41421356 : 1.0));
						if (nd < Dist[v]) { Dist[v] = nd; Queue.Add(v); }
					}
				}
			}
			// At a doorway the clearance is the door's width, not the distance to the jambs' wall.
			for (int32 d = 0; d < R.DoorCentres.Num(); ++d)
			{
				const double DW = d < R.DoorWidths.Num() ? R.DoorWidths[d] : 90.0;
				const double Reach = DW * 0.6 + 25.0;
				int32 cx, cy; CellOf(R.DoorCentres[d], cx, cy);
				const int32 Span = FMath::CeilToInt(Reach / Cell) + 1;
				for (int32 iy = FMath::Max(0, cy - Span); iy <= FMath::Min(NY - 1, cy + Span); ++iy)
				for (int32 ix = FMath::Max(0, cx - Span); ix <= FMath::Min(NX - 1, cx + Span); ++ix)
				{
					const int32 id = iy * NX + ix;
					// The door's own width is judged by its Door feature; the route is judged by what the room puts in the way.
					if (Dist[id] > 0.f && FVector2D::Distance(CellCentre(ix, iy), R.DoorCentres[d]) <= Reach) { Dist[id] = FMath::Max(Dist[id], 150.f); }
				}
			}
			// Door cells: each door centre moved a little into the room.
			TArray<int32> DoorCells;
			for (const FVector2D& Dc : R.DoorCentres)
			{
				const FVector2D Into = (Ctr - Dc).GetSafeNormal();
				int32 ix, iy; CellOf(Dc + Into * 30.0, ix, iy);
				DoorCells.Add(iy * NX + ix);
			}
			if (DoorCells.Num() == 0) { int32 ix, iy; CellOf(FVector2D(Inner.Min.X + 40.0, Ctr.Y), ix, iy); DoorCells.Add(iy * NX + ix); }
			// Widest path from a source: Bottleneck[v] = the largest minimum clearance on any path.
			auto WidestFrom = [&](int32 Src, TArray<float>& Bottle, TArray<int32>& Parent)
			{
				Bottle.Init(-1.f, NX * NY); Parent.Init(-1, NX * NY);
				TArray<uint8> Done; Done.Init(0, NX * NY);
				Bottle[Src] = FMath::Max(Dist[Src], 1.f);
				TArray<int32> Q; Q.Add(Src);
				while (Q.Num() > 0)
				{
					int32 Best = 0; for (int32 k = 1; k < Q.Num(); ++k) { if (Bottle[Q[k]] > Bottle[Q[Best]]) { Best = k; } }
					const int32 u = Q[Best]; Q.RemoveAtSwap(Best);
					if (Done[u]) { continue; }
					Done[u] = 1;
					const int32 ux = u % NX, uy = u / NX;
					for (int32 dy = -1; dy <= 1; ++dy) for (int32 dx = -1; dx <= 1; ++dx)
					{
						if (!dx && !dy) { continue; }
						const int32 vx = ux + dx, vy = uy + dy;
						if (vx < 0 || vy < 0 || vx >= NX || vy >= NY) { continue; }
						const int32 v = vy * NX + vx;
						if (Dist[v] <= 0.f) { continue; }
						const float nb = FMath::Min(Bottle[u], Dist[v]);
						if (nb > Bottle[v]) { Bottle[v] = nb; Parent[v] = u; Q.Add(v); }
					}
				}
			};
			// Shortest path from Src to Target through cells at least MinClear wide (the bottleneck the
			// widest-path search found), so the route is direct rather than a wander along the ridge.
			auto ShortestAtWidth = [&](int32 Src, int32 Target, float MinClear, TArray<int32>& Parent) -> bool
			{
				TArray<float> Cost; Cost.Init(1e9f, NX * NY); Parent.Init(-1, NX * NY);
				TArray<uint8> Done; Done.Init(0, NX * NY);
				Cost[Src] = 0.f;
				TArray<int32> Q; Q.Add(Src);
				while (Q.Num() > 0)
				{
					int32 Best = 0; for (int32 k = 1; k < Q.Num(); ++k) { if (Cost[Q[k]] < Cost[Q[Best]]) { Best = k; } }
					const int32 u = Q[Best]; Q.RemoveAtSwap(Best);
					if (Done[u]) { continue; }
					Done[u] = 1;
					if (u == Target) { return true; }
					const int32 ux = u % NX, uy = u / NX;
					for (int32 dy = -1; dy <= 1; ++dy) for (int32 dx = -1; dx <= 1; ++dx)
					{
						if (!dx && !dy) { continue; }
						const int32 vx = ux + dx, vy = uy + dy;
						if (vx < 0 || vy < 0 || vx >= NX || vy >= NY) { continue; }
						const int32 v = vy * NX + vx;
						if (Dist[v] < MinClear - 0.01f) { continue; }
						// Slightly prefer wider cells so the route keeps to the middle of an aisle.
						const float nc = Cost[u] + static_cast<float>((dx && dy) ? 1.41421356 : 1.0) + 2.0f / FMath::Max(Dist[v], 1.f);
						if (nc < Cost[v]) { Cost[v] = nc; Parent[v] = u; Q.Add(v); }
					}
				}
				return Done[Target] != 0;
			};
			auto EmitPath = [&](const TArray<int32>& Parent, int32 Target, float BottleCm, const FString& Name)
			{
				// Backtrack, convert to points, drop collinear and near points.
				TArray<FVector2D> Pts;
				for (int32 c = Target; c >= 0; c = Parent[c]) { Pts.Add(CellCentre(c % NX, c / NX)); if (Pts.Num() > NX * NY) { break; } }
				if (Pts.Num() < 2) { return; }
				Algo::Reverse(Pts);
				// Douglas-Peucker with a 12 cm tolerance: grid zigzags collapse into a few straight legs.
				TArray<uint8> Keep; Keep.Init(0, Pts.Num()); Keep[0] = 1; Keep[Pts.Num() - 1] = 1;
				TArray<TPair<int32, int32>> Stack; Stack.Add(TPair<int32, int32>(0, Pts.Num() - 1));
				while (Stack.Num() > 0)
				{
					const TPair<int32, int32> Seg = Stack.Pop();
					const FVector2D A = Pts[Seg.Key], B = Pts[Seg.Value];
					const FVector2D AB = B - A; const double L2 = FMath::Max(AB.SizeSquared(), 1e-6);
					double Worst = 0.0; int32 WorstIdx = -1;
					for (int32 k = Seg.Key + 1; k < Seg.Value; ++k)
					{
						const double t = FMath::Clamp(FVector2D::DotProduct(Pts[k] - A, AB) / L2, 0.0, 1.0);
						const double Dd = FVector2D::Distance(Pts[k], A + AB * t);
						if (Dd > Worst) { Worst = Dd; WorstIdx = k; }
					}
					if (WorstIdx >= 0 && Worst > 12.0) { Keep[WorstIdx] = 1; Stack.Add(TPair<int32, int32>(Seg.Key, WorstIdx)); Stack.Add(TPair<int32, int32>(WorstIdx, Seg.Value)); }
				}
				TArray<FVector2D> Simple;
				for (int32 k = 0; k < Pts.Num(); ++k) { if (Keep[k]) { Simple.Add(Pts[k]); } }
				const double W = FMath::Clamp(BottleCm * 2.0, 0.0, FMath::Min(Sz.X, Sz.Y));
				int32 Seg = 0;
				for (int32 k = 0; k + 1 < Simple.Num(); ++k)
				{
					const FVector2D D = Simple[k + 1] - Simple[k];
					const double Len = D.Size();
					if (Len < 5.0) { continue; }
					const FRotator Rot(0.0, FMath::RadiansToDegrees(FMath::Atan2(D.Y, D.X)), 0.0);
					const int32 r = Routes.Add(FTransform(Rot, FVector(Simple[k].X, Simple[k].Y, Z0) + Rot.RotateVector(FVector(0.0, -W * 0.5, 0.0))), FVector::ZeroVector, FVector(Len, W, 0.0), NextSeed());
					Routes.Set(r, RammsPCG::RouteName, FName(*Name));
					Routes.SetInt(r, RammsPCG::SegmentIndex, Seg++);
					Routes.Set(r, RammsPCG::Length, Len);
					Routes.Set(r, RammsPCG::Width, W);
					Routes.Set(r, RammsPCG::FurnitureZone, 0.0);
					Routes.Set(r, RammsPCG::ClearWidth, BottleCm * 2.0);
					Routes.SetBool(r, RammsPCG::bCompliant, BottleCm * 2.0 >= S->MinClearWidth);
					Routes.Set(r, RammsPCG::Threshold, S->MinClearWidth);
					Routes.SetInt(r, RammsPCG::RoomId, R.Id);
				}
			};
			// Pinch points: where a route's clearance is at its minimum, the pieces within reach are the obstacles.
			TArray<FVector2D> Pinches; TArray<double> PinchWidths;
			auto NotePinch = [&](const TArray<int32>& Parent, int32 Target, float BottleCm)
			{
				if (BottleCm * 2.0 >= S->MinClearWidth) { return; }
				for (int32 c = Target; c >= 0; c = Parent[c])
				{
					if (FMath::IsNearlyEqual(Dist[c], BottleCm, 0.01f)) { Pinches.Add(CellCentre(c % NX, c / NX)); PinchWidths.Add(BottleCm * 2.0); break; }
				}
			};
			TArray<float> Bottle; TArray<int32> Parent;
			int32 RouteIdx = 0;
			for (int32 d = 0; d < DoorCells.Num(); ++d)
			{
				WidestFrom(DoorCells[d], Bottle, Parent);
				if (DoorCells.Num() >= 2)
				{
					// Door to the next door around the room.
					const int32 Target = DoorCells[(d + 1) % DoorCells.Num()];
					if (Bottle[Target] > 0.f)
					{
						TArray<int32> Direct; const TArray<int32>& Use = ShortestAtWidth(DoorCells[d], Target, Bottle[Target], Direct) ? Direct : Parent;
						EmitPath(Use, Target, Bottle[Target], FString::Printf(TEXT("Room%d_%s_Route%d"), R.Id, *R.Kind.ToString(), RouteIdx++)); NotePinch(Use, Target, Bottle[Target]);
					}
					else { Pinches.Add(CellCentre(DoorCells[d] % NX, DoorCells[d] / NX)); PinchWidths.Add(0.0); }
					if (d + 1 == DoorCells.Num() && DoorCells.Num() == 2) { break; } // the pair was covered by d = 0
				}
				else
				{
					// One door: to the deepest reachable spot of the room (the widest clearance, far from the door).
					int32 Target = -1; double BestScore = -1.0;
					const FVector2D Dp = CellCentre(DoorCells[d] % NX, DoorCells[d] / NX);
					for (int32 c = 0; c < NX * NY; ++c)
					{
						if (Bottle[c] <= 0.f) { continue; }
						const double Score = FMath::Min(Dist[c], 100.f) * 3.0 + FVector2D::Distance(Dp, CellCentre(c % NX, c / NX)) * 0.5 + Bottle[c];
						if (Score > BestScore) { BestScore = Score; Target = c; }
					}
					if (Target >= 0)
					{
						TArray<int32> Direct; const TArray<int32>& Use = ShortestAtWidth(DoorCells[d], Target, Bottle[Target], Direct) ? Direct : Parent;
						EmitPath(Use, Target, Bottle[Target], FString::Printf(TEXT("Room%d_%s_Route%d"), R.Id, *R.Kind.ToString(), RouteIdx++)); NotePinch(Use, Target, Bottle[Target]);
					}
				}
			}
			// Flag the pieces at the pinch points (and a deliberate intruder that did pinch).
			for (const FEmitted& E : Emitted)
			{
				if (!E.bFloor) { continue; }
				for (int32 k = 0; k < Pinches.Num(); ++k)
				{
					const double Reach = PinchWidths[k] * 0.5 + Cell * 1.5;
					if (DistPointBox(Pinches[k], E.Box) <= Reach)
					{
						Props.Set(E.Point, RammsPCG::ManifestKind, FName(TEXT("Hazard")));
						Props.SetBool(E.Point, RammsPCG::bCompliant, false);
						Props.SetInt(E.Point, RammsPCG::IssueId, static_cast<int32>(ERammsComplianceIssue::ObstacleInRoute));
						Props.Set(E.Point, RammsPCG::Measure, PinchWidths[k]);
						break;
					}
				}
			}
		}
	}

	Pieces.Emit(Context, RammsPCG::PinPieces, { TEXT("Indoor") });
	Primitives.Emit(Context, RammsPCG::PinPrimitives, { TEXT("Indoor") });
	Props.Emit(Context, RammsPCG::PinProps, { TEXT("Indoor") });
	Routes.Emit(Context, RammsPCG::PinRoutes);
	Features.Emit(Context, RammsPCG::PinFeatures);
	return true;
}

#undef LOCTEXT_NAMESPACE
