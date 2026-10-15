// Copyright ATDev. All Rights Reserved.
#include "PCG/PCGRammsHazards.h"

#include "PCGContext.h"
#include "PCGPin.h"
#include "Data/PCGBasePointData.h"
#include "Metadata/PCGMetadata.h"
#include "Metadata/PCGMetadataAttribute.h"

#define LOCTEXT_NAMESPACE "RammsPCG"

namespace
{
	struct FSideReader
	{
		const UPCGBasePointData* Data = nullptr;
		int32 Num = 0;
		explicit FSideReader(const UPCGBasePointData* In) : Data(In)
		{
			if (Data)
			{
				Num = Data->GetNumPoints();
			}
		}
		// Ranges are re-fetched per access: cheap views, and nothing here needs a default constructor.
		FTransform T(int32 i) const { return Data->GetConstTransformValueRange()[i]; }
		FVector Min(int32 i) const { return Data->GetConstBoundsMinValueRange()[i]; }
		FVector Max(int32 i) const { return Data->GetConstBoundsMaxValueRange()[i]; }
		int64 Entry(int32 i) const { return Data->GetConstMetadataEntryValueRange()[i]; }
		double GetD(int32 i, FName Attr, double Default) const
		{
			if (!Data || !Data->Metadata) { return Default; }
			const FPCGMetadataAttributeBase* B = Data->Metadata->GetConstAttribute(Attr);
			if (!B) { return Default; }
			if (B->GetTypeId() == PCG::Private::MetadataTypes<double>::Id) { return static_cast<const FPCGMetadataAttribute<double>*>(B)->GetValueFromItemKey(Entry(i)); }
			if (B->GetTypeId() == PCG::Private::MetadataTypes<float>::Id) { return static_cast<const FPCGMetadataAttribute<float>*>(B)->GetValueFromItemKey(Entry(i)); }
			if (B->GetTypeId() == PCG::Private::MetadataTypes<int32>::Id) { return static_cast<const FPCGMetadataAttribute<int32>*>(B)->GetValueFromItemKey(Entry(i)); }
			return Default;
		}
		FString GetS(int32 i, FName Attr) const
		{
			if (!Data || !Data->Metadata) { return FString(); }
			const FPCGMetadataAttribute<FString>* A = Data->Metadata->GetConstTypedAttribute<FString>(Attr);
			return A ? A->GetValueFromItemKey(Entry(i)) : FString();
		}
		FName GetN(int32 i, FName Attr) const
		{
			if (!Data || !Data->Metadata) { return NAME_None; }
			const FPCGMetadataAttribute<FName>* A = Data->Metadata->GetConstTypedAttribute<FName>(Attr);
			return A ? A->GetValueFromItemKey(Entry(i)) : NAME_None;
		}
		bool GetB(int32 i, FName Attr) const
		{
			if (!Data || !Data->Metadata) { return false; }
			const FPCGMetadataAttribute<bool>* A = Data->Metadata->GetConstTypedAttribute<bool>(Attr);
			return A ? A->GetValueFromItemKey(Entry(i)) : false;
		}
	};

	// Occupancy along one side, in the along-axis coordinate.
	struct FOccupancy
	{
		TArray<FVector2D> Spans;
		bool Free(double A, double B) const
		{
			for (const FVector2D& S : Spans) { if (A < S.Y && B > S.X) { return false; } }
			return true;
		}
		void Take(double A, double B) { Spans.Add(FVector2D(A, B)); }
	};

	void ParseKeepouts(const FString& Keep, FOccupancy& Occ)
	{
		TArray<FString> Parts;
		Keep.ParseIntoArray(Parts, TEXT(";"), true);
		for (const FString& P : Parts)
		{
			FString A, B;
			if (P.Split(TEXT("-"), &A, &B))
			{
				Occ.Take(FCString::Atod(*A), FCString::Atod(*B));
			}
		}
	}

	// Try N random positions for a span of length Len inside [Margin, Length - Margin].
	bool FindFree(const FRandomStream& Rng, const FOccupancy& Occ, double Length, double Len, double Margin, double& OutA)
	{
		for (int32 Try = 0; Try < 12; ++Try)
		{
			const double A = RammsPCG::RandRange(Rng, Margin, FMath::Max(Margin, Length - Margin - Len));
			if (Occ.Free(A, A + Len)) { OutA = A; return true; }
		}
		return false;
	}
}

// --- Hazard Placer ---------------------------------------------------------------------

TArray<FPCGPinProperties> UPCGRammsHazardPlacerSettings::InputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace_GetRef(RammsPCG::PinIn, EPCGDataType::Point, true, true, LOCTEXT("HazardsIn", "Sidewalk sides (Street Network) or path segments (Park Layout)")).SetRequiredPin();
	return Pins;
}

TArray<FPCGPinProperties> UPCGRammsHazardPlacerSettings::OutputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace(RammsPCG::PinProps, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinPieces, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinRoutes, EPCGDataType::Point);
	return Pins;
}

FPCGElementPtr UPCGRammsHazardPlacerSettings::CreateElement() const
{
	return MakeShared<FPCGRammsHazardPlacerElement>();
}

bool FPCGRammsHazardPlacerElement::ExecuteInternal(FPCGContext* Context) const
{
	const UPCGRammsHazardPlacerSettings* S = Context->GetInputSettings<UPCGRammsHazardPlacerSettings>();
	check(S);
	const int32 Seed = Context->GetSeed();
	const URammsWorldPalette* Palette = RammsPCG::LoadPalette(S->Palette, Context);
	const FString MatConcrete = RammsPCG::Mat(Palette, RammsPaletteSlots::MatConcrete);
	const FString MatSidewalk = RammsPCG::Mat(Palette, RammsPaletteSlots::MatSidewalk);
	const FString MatFoliage = RammsPCG::Mat(Palette, RammsPaletteSlots::MatFoliage);
	const FString MatTrunk = RammsPCG::Mat(Palette, RammsPaletteSlots::MatTrunk);
	const FString MatMetal = RammsPCG::Mat(Palette, RammsPaletteSlots::MatMetal);
	const double Intrude = S->NonCompliance <= 0.0 ? 0.0 : FMath::Clamp(S->HazardIntrusionChance * (0.5 + 2.0 * S->NonCompliance), 0.0, 1.0);

	FRammsPointWriter Props, Pieces, Routes;
	int32 Counter = 0;
	auto NextSeed = [&]() { return RammsPCG::SubSeed(Seed, 4000 + (++Counter)); };

	int32 SideIndex = 0;
	for (const FPCGTaggedData& Tagged : Context->InputData.GetInputsByPin(RammsPCG::PinIn))
	{
		FSideReader R(Cast<UPCGBasePointData>(Tagged.Data));
		for (int32 i = 0; i < R.Num; ++i, ++SideIndex)
		{
			FRandomStream Rng(RammsPCG::SubSeed(Seed, 5000 + SideIndex));
			const FTransform& Xf = R.T(i);
			const double Length = R.GetD(i, RammsPCG::Length, (R.Max(i) - R.Min(i)).X);
			const double SW = R.GetD(i, RammsPCG::Width, (R.Max(i) - R.Min(i)).Y);
			const double FZ = FMath::Clamp(R.GetD(i, RammsPCG::FurnitureZone, 0.0), 0.0, SW);
			const double RouteW = R.GetD(i, RammsPCG::RouteWidth, SW - FZ);
			const bool bPark = R.GetB(i, RammsPCG::IsPark);
			const double Yaw = Xf.Rotator().Yaw;
			FName RouteName = R.GetN(i, RammsPCG::RouteName);
			if (RouteName.IsNone()) { RouteName = FName(*FString::Printf(TEXT("Side%d"), SideIndex)); }
			auto ToWorld = [&](double Along, double Across, double Up) { return Xf.TransformPosition(FVector(Along, Across, Up)); };

			FOccupancy Occ;
			ParseKeepouts(R.GetS(i, FName(TEXT("Keepouts"))), Occ);
			Occ.Take(-1e9, 150.0);               // corners
			Occ.Take(Length - 150.0, 1e9);
			double MinClear = RouteW;
			bool bRouteCompliant = RouteW >= S->MinClearWidth;

			// Places an object occupying Across in [y0, y0 + fy] and records compliance.
			auto PlaceAcross = [&](double fy, bool bWantIntrude, double& OutY0, double& OutClear)
			{
				if (bWantIntrude)
				{
					const double Clear = RammsPCG::RandRange(Rng, 55.0, FMath::Max(56.0, S->MinClearWidth - 3.0));
					OutY0 = FMath::Max(0.0, SW - Clear - fy);
					OutClear = FMath::Max(0.0, SW - (OutY0 + fy)); // 0 = blocked: the object is wider than the walk
				}
				else
				{
					const double MaxY0 = FMath::Max(0.0, SW - S->MinClearWidth - fy);
					// Prefer the furniture zone when the object fits in it.
					OutY0 = (fy <= FZ) ? FMath::Max(0.0, (FZ - fy) * 0.5) : RammsPCG::RandRange(Rng, 0.0, MaxY0);
					OutY0 = FMath::Min(OutY0, MaxY0);
					OutClear = FMath::Max(0.0, SW - (OutY0 + fy)); // 0 = blocked: the object is wider than the walk
				}
				MinClear = FMath::Min(MinClear, OutClear);
				bRouteCompliant = bRouteCompliant && OutClear >= S->MinClearWidth;
			};

			// --- trees in the furniture zone -----------------------------------------------
			// In tree pits on paved streets (the grate scaled to fit the zone, the trunk on its centre), straight
			// into the grass on planting-strip streets. A canopy street has large old trees closer together.
			const bool bStrip = S->PlantingStrip > 0.5;
			const bool bCanopy = !bPark && Rng.FRand() < FMath::Clamp(S->CanopyChance, 0.0, 1.0);
			// (On planting-strip streets the lots plant the strip in front of them, around their driveways.)
			if (S->TreeSpacing > 200.0 && FZ >= 80.0 && !bPark && !bStrip)
			{
				const double Spacing = bCanopy ? FMath::Max(S->TreeSpacing * 0.65, 500.0) : S->TreeSpacing;
				for (double a = 450.0; a < Length - 450.0; a += Spacing)
				{
					const double Jit = RammsPCG::RandRange(Rng, -80.0, 80.0);
					const double A = a + Jit;
					if (!Occ.Free(A - 70.0, A + 70.0)) { continue; }
					Occ.Take(A - 90.0, A + 90.0);
					const FVector Base = ToWorld(A, FZ * 0.5, 0.0);
					if (!bStrip)
					{
						FRammsPaletteMesh Pit;
						if (Palette && Palette->PickMesh(RammsPaletteSlots::TreePit, Rng, Pit))
						{
							const double PitMax = FMath::Max(Pit.Footprint.X, Pit.Footprint.Y);
							const double Fit = FMath::Min(1.0, (FZ - 12.0) / FMath::Max(PitMax, 1.0));
							const int32 p = RammsPCG::WritePickedMesh(Props, Pit, Base, Yaw, NextSeed(), Fit);
							RammsPCG::WriteManifest(Props, p, FName(TEXT("Prop")), FName(TEXT("TreePit")), true, ERammsComplianceIssue::None, RouteW, S->MinClearWidth);
						}
					}
					FRammsPaletteMesh Big;
					if (bCanopy && Palette && (Palette->PickMesh(RammsPaletteSlots::TreeLarge, Rng, Big) || Palette->PickMesh(RammsPaletteSlots::Tree, Rng, Big)))
					{
						const int32 p = RammsPCG::WritePickedMesh(Props, Big, Base, RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), RammsPCG::RandRange(Rng, 1.1, 1.4));
						RammsPCG::WriteManifest(Props, p, FName(TEXT("Tree")), FName(TEXT("Canopy")), true, ERammsComplianceIssue::None, 0.0, 0.0);
					}
					else
					{
						RammsPCG::WriteFoliage(Props, Pieces, Palette, RammsPaletteSlots::Tree, Rng, Base, RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(),
							RammsPCG::RandRange(Rng, 300.0, 520.0), RammsPCG::RandRange(Rng, 550.0, 850.0), MatFoliage, MatTrunk, FName(TEXT("Tree")));
					}
				}
			}

			// --- street lights at a regular spacing, staggered between the two sides of a street ---
			if (S->StreetLightSpacing > 300.0 && !bPark && !bStrip)
			{
				FRammsPaletteMesh Lm;
				if (Palette && Palette->PickMesh(RammsPaletteSlots::StreetLight, Rng, Lm))
				{
					const double Sp = S->StreetLightSpacing;
					for (double a = 200.0 + ((SideIndex % 2) ? Sp * 0.5 : 0.0); a < Length - 200.0; a += Sp)
					{
						double A = a;
						if (!Occ.Free(A - 30.0, A + 30.0)) { A += 120.0; if (!Occ.Free(A - 30.0, A + 30.0)) { continue; } }
						Occ.Take(A - 40.0, A + 40.0);
						const double Y = FZ >= 40.0 ? FMath::Min(FZ * 0.5, 45.0) : 30.0;
						const int32 p = RammsPCG::WritePickedMesh(Props, Lm, ToWorld(A, Y, 0.0), Yaw, NextSeed());
						RammsPCG::WriteManifest(Props, p, FName(TEXT("Prop")), RammsPaletteSlots::StreetLight, true, ERammsComplianceIssue::None, RouteW, S->MinClearWidth);
					}
				}
			}

			// --- props ----------------------------------------------------------------------
			const int32 NumProps = FMath::RoundToInt(S->PropDensity * Length / 10000.0 + RammsPCG::RandRange(Rng, -0.4, 0.4));
			for (int32 n = 0; n < NumProps; ++n)
			{
				const double Roll = Rng.FRand();
				FName Slot = RammsPaletteSlots::Bench;
				const bool bResidential = FZ < 50.0 || S->PlantingStrip > 0.5; // no furniture zone or a grass strip: a residential street
				if (Roll < 0.18) { Slot = RammsPaletteSlots::Bench; }
				else if (Roll < 0.34) { Slot = RammsPaletteSlots::TrashBin; }
				else if (Roll < 0.50) { Slot = RammsPaletteSlots::StreetLight; }
				else if (Roll < 0.58) { Slot = RammsPaletteSlots::Hydrant; }
				else if (Roll < 0.66) { Slot = bResidential ? RammsPaletteSlots::Mailbox : RammsPaletteSlots::ParkingMeter; }
				else if (Roll < 0.73) { Slot = bResidential ? RammsPaletteSlots::UtilityPole : RammsPaletteSlots::NewspaperBox; }
				else if (Roll < 0.80) { Slot = RammsPaletteSlots::StreetSign; }
				else if (Roll < 0.88) { Slot = RammsPaletteSlots::Bollard; }
				else if (Roll < 0.95 || Length < 2500.0) { Slot = bResidential ? RammsPaletteSlots::Flowerbed : RammsPaletteSlots::InfoBoard; }
				else { Slot = RammsPaletteSlots::BusStop; }

				FRammsPaletteMesh M;
				if (!Palette || !Palette->PickMesh(Slot, Rng, M))
				{
					// No mesh in the palette: a bollard piece stands in for everything.
					double A; if (!FindFree(Rng, Occ, Length, 40.0, 200.0, A)) { continue; }
					Occ.Take(A - 30.0, A + 70.0);
					FRammsPieceDesc B; B.Kind = ERammsProcPieceKind::Bollard; B.SizeX = 18.0; B.SizeZ = 90.0; B.MaterialPath = MatMetal;
					B.ManifestKind = FName(TEXT("Prop")); B.ManifestSubtype = Slot; B.Measure = RouteW; B.Threshold = S->MinClearWidth;
					B.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(A + 20.0, FMath::Max(FZ * 0.5, 20.0), 0.0)); B.Seed = NextSeed();
					RammsPCG::WritePiece(Pieces, B);
					continue;
				}
				// Seating, shelters and boards turn their front to the walking line (+Y, inward); their
				// footprint depth then runs across the sidewalk and their width along it.
				const bool bFaceIn = Slot == RammsPaletteSlots::Bench || Slot == RammsPaletteSlots::BusStop || Slot == RammsPaletteSlots::InfoBoard;
				const double fx = FMath::Max(bFaceIn ? M.Footprint.Y : M.Footprint.X, 20.0), fy = FMath::Max(bFaceIn ? M.Footprint.X : M.Footprint.Y, 20.0);
				// Furniture is never the thing that narrows a route below the minimum: a shelter that does
				// not fit beside the access route on this sidewalk simply is not placed here.
				if (fy > SW - S->MinClearWidth) { continue; }
				double A; if (!FindFree(Rng, Occ, Length, fx, 200.0, A)) { continue; }
				Occ.Take(A - 20.0, A + fx + 20.0);
				double y0, Clear;
				PlaceAcross(fy, false, y0, Clear);
				const int32 p = RammsPCG::WritePickedMesh(Props, M, ToWorld(A + fx * 0.5, y0 + fy * 0.5, 0.0), Yaw + (bFaceIn ? 90.0 : 0.0), NextSeed());
				RammsPCG::WriteManifest(Props, p, FName(TEXT("Prop")), Slot, Clear >= S->MinClearWidth, Clear >= S->MinClearWidth ? ERammsComplianceIssue::None : ERammsComplianceIssue::ClearWidthBelowMinimum, Clear, S->MinClearWidth);
			}

			// --- hazards ----------------------------------------------------------------------
			const int32 NumHazards = FMath::RoundToInt(S->HazardDensity * Length / 10000.0 + RammsPCG::RandRange(Rng, -0.4, 0.4));
			for (int32 n = 0; n < NumHazards; ++n)
			{
				const double Roll = Rng.FRand();
				FName Type, Slot, Fallback;
				double fx = 60.0, fy = 60.0, fz = 90.0; // fallback piece size
				ERammsProcPieceKind FallbackKind = ERammsProcPieceKind::Planter;
				if (Roll < 0.18)      { Type = FName(TEXT("AFrame"));   Slot = RammsPaletteSlots::HazardAFrame;   Fallback = RammsPaletteSlots::InfoBoard; fx = 60; fy = 70; fz = 100; }
				else if (Roll < 0.32) { Type = FName(TEXT("Scooter"));  Slot = RammsPaletteSlots::HazardScooter;  fx = 120; fy = 45; fz = 35; }
				else if (Roll < 0.40) { Type = FName(TEXT("Bike"));     Slot = RammsPaletteSlots::HazardBike;     Fallback = RammsPaletteSlots::HazardScooter; fx = 180; fy = 60; fz = 100; }
				else if (Roll < 0.52) { Type = FName(TEXT("BinOut"));   Slot = RammsPaletteSlots::HazardBinOut;   Fallback = RammsPaletteSlots::TrashBin; fx = 60; fy = 60; fz = 100; }
				else if (Roll < 0.64) { Type = FName(TEXT("Cafe"));     Slot = RammsPaletteSlots::HazardCafe;     Fallback = RammsPaletteSlots::FurnitureTable; fx = 80; fy = 80; fz = 75; }
				else if (Roll < 0.74) { Type = FName(TEXT("Barrier"));  Slot = RammsPaletteSlots::HazardBarrier;  Fallback = RammsPaletteSlots::Railing; fx = 200; fy = 40; fz = 100; }
				else if (Roll < 0.82) { Type = FName(TEXT("Cone"));     Slot = RammsPaletteSlots::HazardCone;     Fallback = RammsPaletteSlots::Bollard; fx = 40; fy = 40; fz = 75; }
				else if (Roll < 0.88) { Type = FName(TEXT("Box"));      Slot = RammsPaletteSlots::HazardBox;      Fallback = RammsPaletteSlots::HazardBinOut; fx = 50; fy = 40; fz = 40; }
				else if (Roll < 0.92) { Type = FName(TEXT("Dumpster")); Slot = RammsPaletteSlots::HazardDumpster; Fallback = RammsPaletteSlots::HazardBinOut; fx = 180; fy = 90; fz = 140; }
				else                  { Type = FName(TEXT("Upheaval")); Slot = RammsPaletteSlots::HazardUpheaval; FallbackKind = ERammsProcPieceKind::Slab; fx = 120; fy = 120; fz = 3; }

				const bool bIntrude = Rng.FRand() < Intrude;
				if (Type == FName(TEXT("Upheaval")))
				{
					// A heaved slab in the route: the lip is the hazard, not the plan footprint.
					double A; if (!FindFree(Rng, Occ, Length, fx, 200.0, A)) { continue; }
					Occ.Take(A - 10.0, A + fx + 10.0);
					const double Lip = bIntrude ? RammsPCG::RandRange(Rng, 1.5, 5.0) : 0.5;
					const double y0 = FZ + FMath::Max(0.0, (RouteW - fy) * 0.5);
					FRammsPaletteMesh M;
					int32 p = Palette ? RammsPCG::WritePaletteMesh(Props, Palette, Slot, Rng, ToWorld(A + fx * 0.5, y0 + fy * 0.5, 0.0), Yaw, NextSeed(), &M) : -1;
					if (p >= 0)
					{
						RammsPCG::WriteManifest(Props, p, FName(TEXT("Hazard")), Type, Lip <= S->VerticalChangeMax, Lip <= S->VerticalChangeMax ? ERammsComplianceIssue::None : ERammsComplianceIssue::VerticalChangeTooHigh, Lip, S->VerticalChangeMax);
					}
					else
					{
						FRammsPieceDesc Sl; Sl.Kind = ERammsProcPieceKind::Slab; Sl.SizeX = fx; Sl.SizeY = fy; Sl.SizeZ = 20.0 + Lip; Sl.MaterialPath = MatSidewalk;
						Sl.ManifestKind = FName(TEXT("Hazard")); Sl.ManifestSubtype = Type; Sl.Measure = Lip; Sl.Threshold = S->VerticalChangeMax;
						Sl.bCompliant = Lip <= S->VerticalChangeMax; Sl.Issue = Sl.bCompliant ? ERammsComplianceIssue::None : ERammsComplianceIssue::VerticalChangeTooHigh;
						Sl.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(A, y0 + fy * 0.5, Lip)); Sl.Seed = NextSeed();
						RammsPCG::WritePiece(Pieces, Sl);
					}
					if (Lip > S->VerticalChangeMax) { bRouteCompliant = false; }
					continue;
				}

				FRammsPaletteMesh M;
				bool bMesh = Palette && Palette->PickMesh(Slot, Rng, M);
				FName UsedSlot = Slot;
				if (!bMesh && !Fallback.IsNone() && Palette && Palette->PickMesh(Fallback, Rng, M)) { bMesh = true; UsedSlot = Fallback; }
				if (bMesh) { fx = FMath::Max(M.Footprint.X, 20.0); fy = FMath::Max(M.Footprint.Y, 20.0); }
				// An intrusion narrows the route to 55 cm at worst; anything wider than that leaves would
				// block the walk outright, which is not a hazard the manifest can describe, so skip it.
				if (fy > SW - (bIntrude ? 55.0 : S->MinClearWidth)) { continue; }
				double A; if (!FindFree(Rng, Occ, Length, fx, 200.0, A)) { continue; }
				Occ.Take(A - 20.0, A + fx + 20.0);
				double y0, Clear;
				PlaceAcross(fy, bIntrude, y0, Clear);
				const bool bOk = Clear >= S->MinClearWidth;
				const ERammsComplianceIssue Issue = bOk ? ERammsComplianceIssue::None : ERammsComplianceIssue::ClearWidthBelowMinimum;
				if (bMesh)
				{
					const int32 p = RammsPCG::WritePickedMesh(Props, M, ToWorld(A + fx * 0.5, y0 + fy * 0.5, 0.0), Yaw + RammsPCG::RandRange(Rng, -25.0, 25.0), NextSeed());
					RammsPCG::WriteManifest(Props, p, FName(TEXT("Hazard")), Type, bOk, Issue, Clear, S->MinClearWidth);
					if (Type == FName(TEXT("Cafe")))
					{
						// Two chairs flanking the table, same compliance.
						for (int32 c = -1; c <= 1; c += 2)
						{
							int32 q = RammsPCG::WritePaletteMesh(Props, Palette, RammsPaletteSlots::HazardCafeChair, Rng, ToWorld(A + fx * 0.5 + c * (fx * 0.5 + 35.0), y0 + fy * 0.5, 0.0), Yaw + (c > 0 ? 180.0 : 0.0), NextSeed());
							if (q < 0) { q = RammsPCG::WritePaletteMesh(Props, Palette, RammsPaletteSlots::FurnitureChair, Rng, ToWorld(A + fx * 0.5 + c * (fx * 0.5 + 35.0), y0 + fy * 0.5, 0.0), Yaw + (c > 0 ? 180.0 : 0.0), NextSeed()); }
							if (q >= 0) { RammsPCG::WriteManifest(Props, q, FName(TEXT("Hazard")), Type, bOk, Issue, Clear, S->MinClearWidth); Occ.Take(A - 60.0, A + fx + 60.0); }
						}
					}
				}
				else
				{
					FRammsPieceDesc Pl; Pl.Kind = FallbackKind; Pl.SizeX = fx; Pl.SizeY = fy; Pl.SizeZ = fz; Pl.MaterialPath = MatConcrete; Pl.MaterialPath2 = MatFoliage;
					Pl.ManifestKind = FName(TEXT("Hazard")); Pl.ManifestSubtype = Type; Pl.Measure = Clear; Pl.Threshold = S->MinClearWidth; Pl.bCompliant = bOk; Pl.Issue = Issue;
					Pl.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(A, y0 + fy * 0.5, 0.0)); Pl.Seed = NextSeed();
					RammsPCG::WritePiece(Pieces, Pl);
				}
			}

			// --- route record ---------------------------------------------------------------------
			const int32 r = Routes.Add(Xf, FVector(0.0, FZ, 0.0), FVector(Length, SW, 0.0), NextSeed());
			Routes.Set(r, RammsPCG::RouteName, RouteName);
			Routes.Set(r, RammsPCG::Length, Length);
			Routes.Set(r, RammsPCG::Width, RouteW);
			Routes.Set(r, RammsPCG::FurnitureZone, FZ);
			Routes.Set(r, RammsPCG::ClearWidth, MinClear);
			Routes.SetBool(r, RammsPCG::bCompliant, bRouteCompliant);
			Routes.Set(r, RammsPCG::Threshold, S->MinClearWidth);
		}
	}
	Props.Emit(Context, RammsPCG::PinProps, { TEXT("Hazards") });
	Pieces.Emit(Context, RammsPCG::PinPieces, { TEXT("Hazards") });
	Routes.Emit(Context, RammsPCG::PinRoutes);
	return true;
}

// --- Park Layout --------------------------------------------------------------------------

TArray<FPCGPinProperties> UPCGRammsParkLayoutSettings::InputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace_GetRef(RammsPCG::PinIn, EPCGDataType::Point, true, true, LOCTEXT("ParkIn", "Park blocks from Subdivide Lots")).SetRequiredPin();
	return Pins;
}

TArray<FPCGPinProperties> UPCGRammsParkLayoutSettings::OutputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace(RammsPCG::PinPrimitives, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinPieces, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinProps, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinSidewalks, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinFeatures, EPCGDataType::Point);
	return Pins;
}

FPCGElementPtr UPCGRammsParkLayoutSettings::CreateElement() const
{
	return MakeShared<FPCGRammsParkLayoutElement>();
}

bool FPCGRammsParkLayoutElement::ExecuteInternal(FPCGContext* Context) const
{
	const UPCGRammsParkLayoutSettings* S = Context->GetInputSettings<UPCGRammsParkLayoutSettings>();
	check(S);
	const int32 Seed = Context->GetSeed();
	const URammsWorldPalette* Palette = RammsPCG::LoadPalette(S->Palette, Context);
	const FString MatPath = RammsPCG::Mat(Palette, RammsPaletteSlots::MatPath);
	const FString MatCobble = RammsPCG::Mat(Palette, RammsPaletteSlots::MatCobble);
	const FString MatFoliage = RammsPCG::Mat(Palette, RammsPaletteSlots::MatFoliage);
	const FString MatTrunk = RammsPCG::Mat(Palette, RammsPaletteSlots::MatTrunk);
	const FString MatLawn = RammsPCG::Mat(Palette, RammsPaletteSlots::MatLawn);
	auto MatOr = [&](FName Slot, const FString& Fallback) { return Palette && Palette->HasSlot(Slot) ? RammsPCG::Mat(Palette, Slot) : Fallback; };
	const FString MatWater = MatOr(RammsPaletteSlots::MatWater, MatPath);
	const FString MatGravel = MatOr(RammsPaletteSlots::MatGravel, MatPath);
	const FString MatDirt = MatOr(RammsPaletteSlots::MatDirt, MatPath);
	const FString MatMud = MatOr(RammsPaletteSlots::MatMud, MatDirt);

	FRammsPointWriter Primitives, Pieces, Props, Paths, Features;
	int32 Counter = 0;
	auto NextSeed = [&]() { return RammsPCG::SubSeed(Seed, 6000 + (++Counter)); };
	const double PW = FMath::Max(S->PathWidth, 90.0);

	int32 ParkIndex = 0;
	for (const FPCGTaggedData& Tagged : Context->InputData.GetInputsByPin(RammsPCG::PinIn))
	{
		FSideReader R(Cast<UPCGBasePointData>(Tagged.Data));
		for (int32 i = 0; i < R.Num; ++i, ++ParkIndex)
		{
			FRandomStream Rng(RammsPCG::SubSeed(Seed, 7000 + ParkIndex));
			const FVector C = R.T(i).GetLocation();
			const FVector Size = R.Max(i) - R.Min(i);
			const double Z0 = C.Z;
			const double Inset = 300.0 + PW * 0.5;
			const double x0 = C.X - Size.X * 0.5 + Inset, x1 = C.X + Size.X * 0.5 - Inset;
			const double y0 = C.Y - Size.Y * 0.5 + Inset, y1 = C.Y + Size.Y * 0.5 - Inset;
			if (x1 - x0 < 400.0 || y1 - y0 < 400.0) { continue; }

			// Path segments: loop (4) + cross (2). Each is a slab plus a path-side record.
			struct FPathSeg { FVector A, B; double Yaw; };
			const TArray<FPathSeg> Segs = {
				{ FVector(x0, y0, Z0), FVector(x1, y0, Z0), 0.0 }, { FVector(x1, y0, Z0), FVector(x1, y1, Z0), 90.0 },
				{ FVector(x1, y1, Z0), FVector(x0, y1, Z0), 180.0 }, { FVector(x0, y1, Z0), FVector(x0, y0, Z0), 270.0 },
				{ FVector(x0, C.Y, Z0), FVector(x1, C.Y, Z0), 0.0 }, { FVector(C.X, y0, Z0), FVector(C.X, y1, Z0), 90.0 } };
			TArray<FBox2D> PathBoxes;
			int32 SegIndex = 0;
			for (const FPathSeg& Sg : Segs)
			{
				const double Len = FVector::Dist(Sg.A, Sg.B);
				const bool bUneven = Rng.FRand() < S->NonCompliance * 0.5;
				if (bUneven)
				{
					// Cobbles as a slab piece: the cobble material uses mesh UVs, which a scaled cube would stretch.
					FRammsPieceDesc D;
					D.Kind = ERammsProcPieceKind::Slab;
					D.SizeX = Len + PW; D.SizeY = PW; D.SizeZ = 20.0; D.UVScale = 200.0;
					D.MaterialPath = MatCobble;
					D.Transform = FTransform(FRotator(0.0, Sg.Yaw, 0.0), Sg.A - (Sg.B - Sg.A).GetSafeNormal() * (PW * 0.5) + FVector(0, 0, 0.4));
					D.Seed = NextSeed();
					RammsPCG::WritePiece(Pieces, D);
				}
				else
				{
					RammsPCG::WriteCube(Primitives, (Sg.A + Sg.B) * 0.5 + FVector(0, 0, -9.6), FMath::IsNearlyEqual(Sg.Yaw, 0.0) || FMath::IsNearlyEqual(Sg.Yaw, 180.0) ? FVector(Len + PW, PW, 20.0) : FVector(PW, Len + PW, 20.0), 0.0, MatPath, NextSeed());
				}
				PathBoxes.Add(FBox2D(FVector2D(FMath::Min(Sg.A.X, Sg.B.X) - PW, FMath::Min(Sg.A.Y, Sg.B.Y) - PW), FVector2D(FMath::Max(Sg.A.X, Sg.B.X) + PW, FMath::Max(Sg.A.Y, Sg.B.Y) + PW)));
				// Path-side record: origin at the path's left edge so the Hazard Placer's +Y spans the width.
				const FRotator Rot(0.0, Sg.Yaw, 0.0);
				const FVector Left = Rot.RotateVector(FVector(0.0, -PW * 0.5, 0.0));
				const int32 p = Paths.Add(FTransform(Rot, Sg.A + Left), FVector::ZeroVector, FVector(Len, PW, 0.0), NextSeed());
				Paths.Set(p, RammsPCG::Length, Len);
				Paths.Set(p, RammsPCG::Width, PW);
				Paths.Set(p, RammsPCG::FurnitureZone, 0.0);
				Paths.Set(p, RammsPCG::RouteWidth, PW);
				Paths.SetBool(p, RammsPCG::IsPark, true);
				Paths.Set(p, RammsPCG::RouteName, FName(*FString::Printf(TEXT("Park%d_Path%d"), ParkIndex, SegIndex)));
				if (bUneven)
				{
					const int32 f = Features.AddBox((Sg.A + Sg.B) * 0.5, Sg.Yaw, FVector(Len, PW, 2.0), NextSeed());
					RammsPCG::WriteManifest(Features, f, FName(TEXT("Surface")), FName(TEXT("Cobbled")), false, ERammsComplianceIssue::SurfaceUneven, 1.0, 0.64);
				}
				// Benches on the lawn beside the path, facing it.
				for (double a = S->BenchSpacing * 0.5; a < Len - 200.0; a += FMath::Max(S->BenchSpacing, 400.0))
				{
					// Bench on the -Y side of the path, its front (+X after the facing offset) turned to +Y = the path.
					const FVector P = Sg.A + Rot.RotateVector(FVector(a, -PW * 0.5 - 60.0, 0.0));
					const int32 b = RammsPCG::WritePaletteMesh(Props, Palette, RammsPaletteSlots::Bench, Rng, P, Sg.Yaw + 90.0, NextSeed());
					if (b >= 0) { RammsPCG::WriteManifest(Props, b, FName(TEXT("Prop")), FName(TEXT("Bench")), true, ERammsComplianceIssue::None, PW, S->MinClearWidth); }
				}
				++SegIndex;
			}

			// The lawn between the paths is not flat: each quadrant gets a pond (one per park), grassy mounds,
			// boulders, and patches of gravel, dirt or mud; the crossing is a cobbled plaza.
			struct FMound { FVector2D C; double SX, SY, Hm; };
			TArray<FMound> Mounds;
			TArray<FBox2D> Avoid; // ponds and patches: no trees or grass clumps
			auto GroundZ = [&](const FVector2D& P)
			{
				double Z = Z0;
				for (const FMound& Mn : Mounds)
				{
					const double E = FMath::Sqrt(FMath::Square(2.0 * (P.X - Mn.C.X) / Mn.SX) + FMath::Square(2.0 * (P.Y - Mn.C.Y) / Mn.SY));
					if (E < 1.0) { Z = FMath::Max(Z, Z0 + Mn.Hm * 0.5 * (1.0 + FMath::Cos(PI * E)) - 2.0); }
				}
				return Z;
			};
			auto RockAt = [&](const FVector2D& P, double ScaleLo, double ScaleHi)
			{
				FRammsPaletteMesh Rk;
				if (!Palette || !Palette->PickMesh(RammsPaletteSlots::Rock, Rng, Rk)) { return; }
				const double K = RammsPCG::RandRange(Rng, ScaleLo, ScaleHi);
				// Sunk a little into the ground so it does not sit on it like a prop.
				const int32 r = RammsPCG::WritePickedMesh(Props, Rk, FVector(P.X, P.Y, GroundZ(P) - Rk.Height * K * 0.15), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), K);
				if (r >= 0) { RammsPCG::WriteManifest(Props, r, FName(TEXT("Prop")), FName(TEXT("Rock")), true, ERammsComplianceIssue::None, 0.0, 0.0); }
			};
			auto Patch = [&](const FVector2D& P, double SX, double SY, double Top, const FString& Mat, FName Sub)
			{
				FRammsPieceDesc D;
				D.Kind = ERammsProcPieceKind::Patch;
				D.SizeX = SX; D.SizeY = SY; D.SizeZ = Top; D.UVScale = 300.0;
				D.MaterialPath = Mat;
				D.ManifestKind = Sub == FName(TEXT("Pond")) ? FName(TEXT("Water")) : FName(TEXT("Surface"));
				D.ManifestSubtype = Sub;
				D.Measure = FMath::Min(SX, SY);
				D.Transform = FTransform(FRotator(0.0, RammsPCG::RandRange(Rng, 0.0, 180.0), 0.0), FVector(P.X, P.Y, Z0));
				D.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, D);
				Avoid.Add(FBox2D(P - FVector2D(FMath::Max(SX, SY) * 0.5), P + FVector2D(FMath::Max(SX, SY) * 0.5)));
			};
			{
				const double M = PW * 0.5 + 160.0; // keep clear of paths and the benches beside them
				const FBox2D Quads[4] = {
					FBox2D(FVector2D(x0 + M, y0 + M), FVector2D(C.X - M, C.Y - M)), FBox2D(FVector2D(C.X + M, y0 + M), FVector2D(x1 - M, C.Y - M)),
					FBox2D(FVector2D(x0 + M, C.Y + M), FVector2D(C.X - M, y1 - M)), FBox2D(FVector2D(C.X + M, C.Y + M), FVector2D(x1 - M, y1 - M)) };
				const int32 PondQuad = Rng.RandRange(0, 3);
				for (int32 q = 0; q < 4; ++q)
				{
					const FBox2D& Q = Quads[q];
					const FVector2D Qs = Q.GetSize();
					if (Qs.X < 300.0 || Qs.Y < 300.0) { continue; }
					const FVector2D Qc = Q.GetCenter();
					if (q == PondQuad && Qs.X > 700.0 && Qs.Y > 700.0)
					{
						// Pond: water in a ring of mud, edged with boulders.
						const double SX = Qs.X * RammsPCG::RandRange(Rng, 0.45, 0.7), SY = Qs.Y * RammsPCG::RandRange(Rng, 0.45, 0.7);
						Patch(Qc, SX + 120.0, SY + 120.0, 0.8, MatMud, FName(TEXT("Mud")));
						Patch(Qc, SX, SY, 1.6, MatWater, FName(TEXT("Pond")));
						const int32 NR = FMath::Clamp(static_cast<int32>((SX + SY) / 90.0), 6, 30);
						for (int32 k = 0; k < NR; ++k)
						{
							if (Rng.FRand() < 0.35) { continue; }
							const double A = 2.0 * PI * k / NR + RammsPCG::RandRange(Rng, -0.1, 0.1);
							RockAt(Qc + FVector2D(FMath::Cos(A) * (SX * 0.5 + 25.0), FMath::Sin(A) * (SY * 0.5 + 25.0)), 0.5, 1.1);
						}
						continue;
					}
					// One or two mounds.
					const int32 NM = Qs.X * Qs.Y > 1200.0 * 1200.0 ? 2 : 1;
					for (int32 k = 0; k < NM; ++k)
					{
						const double SX = FMath::Min(Qs.X * RammsPCG::RandRange(Rng, 0.5, 0.85), 1800.0), SY = FMath::Min(Qs.Y * RammsPCG::RandRange(Rng, 0.5, 0.85), 1800.0);
						const FVector2D Mc(RammsPCG::RandRange(Rng, Q.Min.X + SX * 0.5, FMath::Max(Q.Min.X + SX * 0.5, Q.Max.X - SX * 0.5)), RammsPCG::RandRange(Rng, Q.Min.Y + SY * 0.5, FMath::Max(Q.Min.Y + SY * 0.5, Q.Max.Y - SY * 0.5)));
						const double Hm = FMath::Min(SX, SY) * RammsPCG::RandRange(Rng, 0.06, 0.12);
						Mounds.Add({ Mc, SX, SY, Hm });
						FRammsPieceDesc D;
						D.Kind = ERammsProcPieceKind::Mound;
						D.SizeX = SX; D.SizeY = SY; D.Rise = Hm; D.UVScale = 300.0;
						D.MaterialPath = MatLawn;
						D.ManifestKind = FName(TEXT("Terrain")); D.ManifestSubtype = FName(TEXT("Mound"));
						D.Measure = Hm * PI / FMath::Min(SX, SY); // steepest grade of the cosine bump
						D.Transform = FTransform(FRotator::ZeroRotator, FVector(Mc.X, Mc.Y, Z0));
						D.Seed = NextSeed();
						RammsPCG::WritePiece(Pieces, D);
						if (Rng.FRand() < 0.5) { for (int32 r = 0; r < 3; ++r) { RockAt(Mc + FVector2D(RammsPCG::RandRange(Rng, -SX, SX) * 0.3, RammsPCG::RandRange(Rng, -SY, SY) * 0.3), 0.6, 1.4); } }
					}
					// A ground patch: gravel, dirt (worn grass) or mud, away from the mounds' tops.
					{
						static const TCHAR* Subs[3] = { TEXT("Gravel"), TEXT("Dirt"), TEXT("Mud") };
						const int32 Pk = Rng.RandRange(0, 2);
						const FString& Mat = Pk == 0 ? MatGravel : (Pk == 1 ? MatDirt : MatMud);
						const double SX = RammsPCG::RandRange(Rng, 150.0, 400.0), SY = RammsPCG::RandRange(Rng, 120.0, 300.0);
						const FVector2D Pc(RammsPCG::RandRange(Rng, Q.Min.X + 150.0, Q.Max.X - 150.0), RammsPCG::RandRange(Rng, Q.Min.Y + 150.0, Q.Max.Y - 150.0));
						if (GroundZ(Pc) <= Z0 + 1.0) { Patch(Pc, SX, SY, 0.6, Mat, FName(Subs[Pk])); }
					}
					// A boulder group.
					{
						const FVector2D Gc(RammsPCG::RandRange(Rng, Q.Min.X + 80.0, Q.Max.X - 80.0), RammsPCG::RandRange(Rng, Q.Min.Y + 80.0, Q.Max.Y - 80.0));
						const int32 NR = Rng.RandRange(1, 4);
						for (int32 r = 0; r < NR; ++r) { RockAt(Gc + FVector2D(RammsPCG::RandRange(Rng, -90.0, 90.0), RammsPCG::RandRange(Rng, -90.0, 90.0)), 0.5, 1.5); }
					}
				}
				// A gravel trail cutting across one quadrant, path edge to path edge (a desire line).
				{
					const int32 q = (PondQuad + 1 + Rng.RandRange(0, 2)) % 4;
					const FBox2D& Q = Quads[q];
					if (Q.GetSize().X > 400.0 && Q.GetSize().Y > 400.0)
					{
						const FVector2D A2(Q.Min.X - 100.0, Q.Min.Y - 100.0), B2(Q.Max.X + 100.0, Q.Max.Y + 100.0);
						const bool bFlip = Rng.FRand() < 0.5;
						const FVector2D Ta = bFlip ? FVector2D(A2.X, B2.Y) : A2, Tb = bFlip ? FVector2D(B2.X, A2.Y) : B2;
						const double TLen = (Tb - Ta).Size();
						const double TYaw = FMath::RadiansToDegrees(FMath::Atan2(Tb.Y - Ta.Y, Tb.X - Ta.X));
						const FVector2D Tc = (Ta + Tb) * 0.5;
						bool bClear = true;
						for (const FMound& Mn : Mounds) { if ((Mn.C - Tc).Size() < FMath::Max(Mn.SX, Mn.SY) * 0.5 + 80.0) { bClear = false; } }
						if (bClear)
						{
							// A slab piece rather than a cube instance: pack ground materials use mesh UVs, which a long
							// scaled cube would stretch; the piece's world box-projected UVs keep the gravel at scale.
							FRammsPieceDesc D;
							D.Kind = ERammsProcPieceKind::Slab;
							D.SizeX = TLen; D.SizeY = 110.0; D.SizeZ = 20.0; D.UVScale = 250.0;
							D.MaterialPath = MatGravel;
							D.ManifestKind = FName(TEXT("Surface")); D.ManifestSubtype = FName(TEXT("GravelTrail"));
							D.bCompliant = false; D.Issue = ERammsComplianceIssue::SurfaceUneven; D.Measure = 110.0; D.Threshold = S->MinClearWidth;
							D.Transform = FTransform(FRotator(0.0, TYaw, 0.0), FVector(Ta.X, Ta.Y, Z0 + 0.6));
							D.Seed = NextSeed();
							RammsPCG::WritePiece(Pieces, D);
							for (double t = 0.0; t <= 1.0; t += 0.1) { const FVector2D P = Ta + (Tb - Ta) * t; Avoid.Add(FBox2D(P - FVector2D(70.0), P + FVector2D(70.0))); }
						}
					}
				}
				// Cobbled plaza where the cross paths meet.
				{
					FRammsPieceDesc D;
					D.Kind = ERammsProcPieceKind::Slab;
					D.SizeX = PW * 3.0; D.SizeY = PW * 3.0; D.SizeZ = 20.0; D.UVScale = 200.0;
					D.MaterialPath = MatCobble;
					D.Transform = FTransform(FRotator::ZeroRotator, FVector(C.X - PW * 1.5, C.Y, Z0 + 0.6));
					D.Seed = NextSeed();
					RammsPCG::WritePiece(Pieces, D);
				}
			}

			// Grass clumps over the lawn, off the paths.
			if (S->GrassDensity > 0.0 && Palette && Palette->HasSlot(RammsPaletteSlots::GrassClump))
			{
				const double Step = 100.0 / FMath::Sqrt(FMath::Max(S->GrassDensity, 0.05));
				for (double gx = C.X - Size.X * 0.5 + 60.0; gx < C.X + Size.X * 0.5 - 60.0; gx += Step)
				{
					for (double gy = C.Y - Size.Y * 0.5 + 60.0; gy < C.Y + Size.Y * 0.5 - 60.0; gy += Step)
					{
						const FVector2D P(gx + RammsPCG::RandRange(Rng, -Step * 0.45, Step * 0.45), gy + RammsPCG::RandRange(Rng, -Step * 0.45, Step * 0.45));
						bool bOnPath = false;
						for (const FBox2D& B : PathBoxes) { if (B.ExpandBy(-PW * 0.35).IsInside(P)) { bOnPath = true; break; } }
						for (const FBox2D& B : Avoid) { if (B.IsInside(P)) { bOnPath = true; break; } }
						if (bOnPath) { continue; }
						FRammsPaletteMesh G; if (!Palette->PickMesh(RammsPaletteSlots::GrassClump, Rng, G)) { break; }
						RammsPCG::WritePickedMesh(Props, G, FVector(P.X, P.Y, GroundZ(P)), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), RammsPCG::RandRange(Rng, 0.7, 1.3));
						// Two short tufts around each clump.
						for (int32 k = 0; k < 2; ++k)
						{
							FRammsPaletteMesh Tf; if (!Palette->PickMesh(RammsPaletteSlots::LawnTuft, Rng, Tf)) { break; }
							const FVector2D Q(P.X + RammsPCG::RandRange(Rng, -Step * 0.5, Step * 0.5), P.Y + RammsPCG::RandRange(Rng, -Step * 0.5, Step * 0.5));
							bool bBad = false;
							for (const FBox2D& B : PathBoxes) { if (B.ExpandBy(-PW * 0.35).IsInside(Q)) { bBad = true; break; } }
							for (const FBox2D& B : Avoid) { if (B.IsInside(Q)) { bBad = true; break; } }
							if (bBad) { continue; }
							RammsPCG::WritePickedMesh(Props, Tf, FVector(Q.X, Q.Y, GroundZ(Q)), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), RammsPCG::RandRange(Rng, 0.45, 0.9));
						}
					}
				}
			}
			// Trees and shrubs on the lawn, off the paths.
			const double AreaM2 = Size.X * Size.Y / 10000.0;
			const int32 NumTrees = FMath::RoundToInt(S->FoliageDensity * AreaM2 / 100.0);
			for (int32 t = 0; t < NumTrees * 2; ++t)
			{
				const FVector2D P(RammsPCG::RandRange(Rng, C.X - Size.X * 0.5 + 200.0, C.X + Size.X * 0.5 - 200.0), RammsPCG::RandRange(Rng, C.Y - Size.Y * 0.5 + 200.0, C.Y + Size.Y * 0.5 - 200.0));
				bool bOnPath = false;
				for (const FBox2D& B : PathBoxes) { if (B.IsInside(P)) { bOnPath = true; break; } }
				for (const FBox2D& B : Avoid) { if (B.ExpandBy(100.0).IsInside(P)) { bOnPath = true; break; } }
				if (bOnPath) { continue; }
				const bool bShrub = (t % 2) == 1;
				RammsPCG::WriteFoliage(Props, Pieces, Palette, bShrub ? RammsPaletteSlots::Shrub : (Rng.FRand() < 0.3 ? RammsPaletteSlots::TreeSmall : RammsPaletteSlots::Tree), Rng,
					FVector(P.X, P.Y, GroundZ(P) - 3.0), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(),
					bShrub ? RammsPCG::RandRange(Rng, 60.0, 140.0) : RammsPCG::RandRange(Rng, 350.0, 700.0),
					bShrub ? RammsPCG::RandRange(Rng, 50.0, 110.0) : RammsPCG::RandRange(Rng, 600.0, 1100.0),
					MatFoliage, MatTrunk, bShrub ? FName(TEXT("Shrub")) : FName(TEXT("Tree")));
			}
		}
	}
	Primitives.Emit(Context, RammsPCG::PinPrimitives, { TEXT("Park") });
	Pieces.Emit(Context, RammsPCG::PinPieces, { TEXT("Park") });
	Props.Emit(Context, RammsPCG::PinProps, { TEXT("Park") });
	Paths.Emit(Context, RammsPCG::PinSidewalks);
	Features.Emit(Context, RammsPCG::PinFeatures);
	return true;
}

#undef LOCTEXT_NAMESPACE
