// Copyright ATDev. All Rights Reserved.
#include "PCG/PCGRammsLots.h"

#include "PCGContext.h"
#include "PCGPin.h"
#include "Data/PCGBasePointData.h"
#include "Metadata/PCGMetadata.h"
#include "Metadata/PCGMetadataAttribute.h"

#define LOCTEXT_NAMESPACE "RammsPCG"

namespace
{
	// Read helpers over an input point data. Missing attributes give defaults so
	// a graph can feed these nodes from hand-made points too.
	struct FPointReader
	{
		const UPCGBasePointData* Data = nullptr;
		int32 Num = 0;

		explicit FPointReader(const UPCGBasePointData* In) : Data(In)
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
		template <typename T> T Get(int32 i, FName Attr, const T& Default) const
		{
			if (!Data || !Data->Metadata) { return Default; }
			const FPCGMetadataAttribute<T>* A = Data->Metadata->GetConstTypedAttribute<T>(Attr);
			return A ? A->GetValueFromItemKey(Entry(i)) : Default;
		}
		double GetD(int32 i, FName Attr, double Default) const
		{
			if (!Data || !Data->Metadata) { return Default; }
			const FPCGMetadataAttributeBase* B = Data->Metadata->GetConstAttribute(Attr);
			if (!B) { return Default; }
			if (B->GetTypeId() == PCG::Private::MetadataTypes<double>::Id) { return static_cast<const FPCGMetadataAttribute<double>*>(B)->GetValueFromItemKey(Entry(i)); }
			if (B->GetTypeId() == PCG::Private::MetadataTypes<float>::Id) { return static_cast<const FPCGMetadataAttribute<float>*>(B)->GetValueFromItemKey(Entry(i)); }
			if (B->GetTypeId() == PCG::Private::MetadataTypes<int32>::Id) { return static_cast<const FPCGMetadataAttribute<int32>*>(B)->GetValueFromItemKey(Entry(i)); }
			if (B->GetTypeId() == PCG::Private::MetadataTypes<int64>::Id) { return static_cast<double>(static_cast<const FPCGMetadataAttribute<int64>*>(B)->GetValueFromItemKey(Entry(i))); }
			return Default;
		}
		FVector Size(int32 i) const { return Max(i) - Min(i); }
	};

	// --- facade module kits ------------------------------------------------------------------
	// Module meshes have their pivot at the start of the run (local x = 0..L), the facade plane on
	// local y = 0 with the exterior toward +y, and the base on z = 0. Corner pieces (L1) cover the
	// last 100 cm of a face and the first 100 cm of the next one, which turns toward local -y.
	constexpr double CornerLen = 100.0;

	struct FFacadeKit
	{
		FString Style, UpperStyle;
		const TArray<FRammsPaletteMesh>* GF = nullptr;
		const TArray<FRammsPaletteMesh>* GFDoor = nullptr;
		const TArray<FRammsPaletteMesh>* GFCorner = nullptr;
		const TArray<FRammsPaletteMesh>* Win = nullptr;
		const TArray<FRammsPaletteMesh>* WinTop = nullptr;
		const TArray<FRammsPaletteMesh>* WinCorner = nullptr;
		const TArray<FRammsPaletteMesh>* Top = nullptr;
		const TArray<FRammsPaletteMesh>* TopCorner = nullptr;
		double GFHeight = 0.0, WinHeight = 300.0, TopHeight = 50.0;
	};

	TArray<double> ModuleLengths(const TArray<FRammsPaletteMesh>* Meshes)
	{
		TArray<double> Lens;
		if (Meshes)
		{
			for (const FRammsPaletteMesh& M : *Meshes)
			{
				const double L = FMath::RoundToDouble(M.Footprint.X / 100.0) * 100.0;
				if (L >= 100.0 && !Lens.Contains(L)) { Lens.Add(L); }
			}
		}
		Lens.Sort();
		return Lens;
	}

	bool PickModule(const TArray<FRammsPaletteMesh>* Meshes, double L, const FRandomStream& Rng, FRammsPaletteMesh& Out)
	{
		if (!Meshes) { return false; }
		TArray<const FRammsPaletteMesh*> C;
		for (const FRammsPaletteMesh& M : *Meshes)
		{
			if (FMath::Abs(M.Footprint.X - L) < 6.0 && !M.Mesh.IsNull()) { C.Add(&M); }
		}
		if (C.Num() == 0) { return false; }
		Out = *C[FMath::Clamp(static_cast<int32>(Rng.FRand() * C.Num()), 0, C.Num() - 1)];
		return true;
	}

	// Split Fill (a multiple of 100) into module lengths; false when the kit cannot tile it.
	bool TileRun(double Fill, const TArray<double>& Lens, const FRandomStream& Rng, TArray<double>& Out)
	{
		Out.Reset();
		if (Lens.Num() == 0) { return false; }
		const double MinLen = Lens[0];
		double Rem = Fill;
		int32 Guard = 0;
		while (Rem > 1.0 && ++Guard < 200)
		{
			TArray<double> C;
			for (double L : Lens)
			{
				const double R = Rem - L;
				if (R > -1.0 && (FMath::Abs(R) < 1.0 || R >= MinLen - 1.0)) { C.Add(L); }
			}
			if (C.Num() == 0) { return false; }
			const double L = C[FMath::Clamp(static_cast<int32>(Rng.FRand() * C.Num()), 0, C.Num() - 1)];
			Out.Add(L);
			Rem -= L;
		}
		return Rem <= 1.0;
	}

	double MeshesHeight(const TArray<FRammsPaletteMesh>* Meshes, double Default)
	{
		if (!Meshes || Meshes->Num() == 0) { return Default; }
		return FMath::RoundToDouble((*Meshes)[0].Height / 50.0) * 50.0;
	}

	bool BuildKit(const URammsWorldPalette* Palette, const FString& StyleList, const FRandomStream& Rng, FFacadeKit& Kit)
	{
		if (!Palette) { return false; }
		TArray<FString> Allowed;
		StyleList.ParseIntoArray(Allowed, TEXT(","), true);
		for (FString& A : Allowed) { A.TrimStartAndEndInline(); }
		TArray<FString> Styles;
		for (const FString& St : Palette->FacadeStyles())
		{
			if (Allowed.Num() == 0 || Allowed.Contains(St))
			{
				// A usable style tiles any 100-multiple >= 300 on the ground floor and the upper floors.
				const TArray<double> GfL = ModuleLengths(Palette->GetMeshes(URammsWorldPalette::FacadeSlot(St, RammsPaletteSlots::FacadePartGF)));
				const TArray<double> WinL = ModuleLengths(Palette->GetMeshes(URammsWorldPalette::FacadeSlot(St, RammsPaletteSlots::FacadePartWin)));
				if (GfL.Num() >= 2 && WinL.Num() >= 2 && Palette->GetMeshes(URammsWorldPalette::FacadeSlot(St, RammsPaletteSlots::FacadePartGFCorner)))
				{
					Styles.Add(St);
				}
			}
		}
		if (Styles.Num() == 0) { return false; }
		Kit.Style = Styles[FMath::Clamp(static_cast<int32>(Rng.FRand() * Styles.Num()), 0, Styles.Num() - 1)];
		Kit.UpperStyle = (Rng.FRand() < 0.65) ? Kit.Style : Styles[FMath::Clamp(static_cast<int32>(Rng.FRand() * Styles.Num()), 0, Styles.Num() - 1)];
		Kit.GF = Palette->GetMeshes(URammsWorldPalette::FacadeSlot(Kit.Style, RammsPaletteSlots::FacadePartGF));
		Kit.GFDoor = Palette->GetMeshes(URammsWorldPalette::FacadeSlot(Kit.Style, RammsPaletteSlots::FacadePartGFDoor));
		Kit.GFCorner = Palette->GetMeshes(URammsWorldPalette::FacadeSlot(Kit.Style, RammsPaletteSlots::FacadePartGFCorner));
		Kit.Win = Palette->GetMeshes(URammsWorldPalette::FacadeSlot(Kit.UpperStyle, RammsPaletteSlots::FacadePartWin));
		Kit.WinTop = Palette->GetMeshes(URammsWorldPalette::FacadeSlot(Kit.UpperStyle, RammsPaletteSlots::FacadePartWinTop));
		Kit.WinCorner = Palette->GetMeshes(URammsWorldPalette::FacadeSlot(Kit.UpperStyle, RammsPaletteSlots::FacadePartWinCorner));
		if (!Kit.WinCorner) { Kit.WinCorner = Palette->GetMeshes(RammsPaletteSlots::FacadeWinCornerGeneric); }
		const bool bTall = Rng.FRand() < 0.5;
		Kit.Top = Palette->GetMeshes(bTall ? RammsPaletteSlots::FacadeTallTop : RammsPaletteSlots::FacadeTop);
		Kit.TopCorner = Palette->GetMeshes(bTall ? RammsPaletteSlots::FacadeTallTopCorner : RammsPaletteSlots::FacadeTopCorner);
		if (!Kit.Top) { Kit.Top = Palette->GetMeshes(RammsPaletteSlots::FacadeTop); Kit.TopCorner = Palette->GetMeshes(RammsPaletteSlots::FacadeTopCorner); }
		Kit.GFHeight = MeshesHeight(Kit.GF, 900.0);
		Kit.WinHeight = MeshesHeight(Kit.Win, 300.0);
		Kit.TopHeight = Kit.Top ? MeshesHeight(Kit.Top, 50.0) : 0.0;
		return Kit.GF && Kit.GFCorner && Kit.Win;
	}

	// One material pick per category for a whole building, from the palette's Facade.Mat.* sets.
	TMap<FName, FString> PickFacadeMaterials(const URammsWorldPalette* Palette, const FRandomStream& Rng)
	{
		TMap<FName, FString> Mats;
		for (const TPair<FName, FRammsPaletteSlot>& Pair : Palette->Slots)
		{
			const FString Key = Pair.Key.ToString();
			if (Key.StartsWith(RammsPaletteSlots::FacadeMatPrefix))
			{
				const FString Path = Palette->PickMaterialPath(Pair.Key, Rng);
				if (!Path.IsEmpty()) { Mats.Add(FName(*Key.Mid(RammsPaletteSlots::FacadeMatPrefix.Len())), Path); }
			}
		}
		// The ground floor's big panels take their own brick set when the palette has one.
		const FString* Bricks = Mats.Find(FName(TEXT("Bricks")));
		if (Bricks)
		{
			if (!Mats.Contains(FName(TEXT("Bricks2")))) { Mats.Add(FName(TEXT("Bricks2")), *Bricks); }
			Mats.Add(FName(TEXT("Default")), *Bricks);
		}
		return Mats;
	}

	int32 WriteModule(FRammsPointWriter& W, const FRammsPaletteMesh& M, const FTransform& Xf, const TMap<FName, FString>& Mats, int32 Seed)
	{
		const int32 i = W.Add(Xf, FVector(0.0, -M.Footprint.Y, 0.0), FVector(M.Footprint.X, M.Footprint.Y, M.Height), Seed);
		W.SetPath(i, RammsPCG::Mesh, M.Mesh.ToSoftObjectPath());
		const FString* Fallback = Mats.Find(FName(TEXT("Default")));
		for (int32 s = 0; s < RammsPCG::NumModuleMaterials; ++s)
		{
			const FString* Path = M.MaterialSlots.IsValidIndex(s) ? Mats.Find(M.MaterialSlots[s]) : nullptr;
			if (!Path) { Path = Fallback; }
			W.SetPath(i, RammsPCG::ModuleMaterial(s), Path ? FSoftObjectPath(*Path) : FSoftObjectPath());
		}
		return i;
	}
}

// --- Subdivide Lots ----------------------------------------------------------------

TArray<FPCGPinProperties> UPCGRammsSubdivideLotsSettings::InputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace_GetRef(RammsPCG::PinIn, EPCGDataType::Point, true, true, LOCTEXT("LotsIn", "Blocks from Street Network")).SetRequiredPin();
	return Pins;
}

TArray<FPCGPinProperties> UPCGRammsSubdivideLotsSettings::OutputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace(RammsPCG::PinLots, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinParks, EPCGDataType::Point);
	return Pins;
}

FPCGElementPtr UPCGRammsSubdivideLotsSettings::CreateElement() const
{
	return MakeShared<FPCGRammsSubdivideLotsElement>();
}

bool FPCGRammsSubdivideLotsElement::ExecuteInternal(FPCGContext* Context) const
{
	const UPCGRammsSubdivideLotsSettings* S = Context->GetInputSettings<UPCGRammsSubdivideLotsSettings>();
	check(S);
	const int32 Seed = Context->GetSeed();
	FRammsPointWriter Lots, Parks;
	int32 LotId = 0;

	for (const FPCGTaggedData& Tagged : Context->InputData.GetInputsByPin(RammsPCG::PinIn))
	{
		FPointReader R(Cast<UPCGBasePointData>(Tagged.Data));
		for (int32 i = 0; i < R.Num; ++i)
		{
			const int32 BlockId = static_cast<int32>(R.GetD(i, RammsPCG::BlockId, i));
			const bool bPark = R.Get<bool>(i, RammsPCG::IsPark, false);
			const FVector Centre = R.T(i).GetLocation();
			const FVector Size = R.Size(i);
			if (bPark || Size.X < S->LotWidthMin || Size.Y < 300.0)
			{
				const int32 p = Parks.Add(R.T(i), R.Min(i), R.Max(i), RammsPCG::SubSeed(Seed, 500 + BlockId));
				Parks.SetInt(p, RammsPCG::BlockId, BlockId);
				Parks.Set(p, RammsPCG::Width, Size.X);
				Parks.Set(p, RammsPCG::Depth, Size.Y);
				Parks.SetBool(p, RammsPCG::IsPark, true);
				continue;
			}
			FRandomStream Rng(RammsPCG::SubSeed(Seed, 700 + BlockId));
			const bool bTwoRows = Size.Y > 2.0 * S->MinLotDepth;
			const int32 Rows = bTwoRows ? 2 : 1;
			const double RowDepth = Size.Y / Rows;
			for (int32 Row = 0; Row < Rows; ++Row)
			{
				// Row 0 faces south (-Y), row 1 faces north (+Y).
				const double FaceSign = (Row == 0) ? -1.0 : 1.0;
				const double Yaw = (Row == 0) ? -90.0 : 90.0; // +X -> -Y, or +X -> +Y
				const double RowY = Centre.Y - Size.Y * 0.5 + RowDepth * (Row + 0.5);
				double x = Centre.X - Size.X * 0.5;
				const double xEnd = Centre.X + Size.X * 0.5;
				while (xEnd - x > S->LotWidthMin * 0.5)
				{
					double W = RammsPCG::RandRange(Rng, S->LotWidthMin, S->LotWidthMax);
					if (xEnd - (x + W) < S->LotWidthMin * 0.6) { W = xEnd - x; }
					const FVector LotCentre(x + W * 0.5, RowY, Centre.Z);
					// Local frame: +X toward the street (depth axis), Y along the frontage (width).
					const int32 l = Lots.Add(FTransform(FRotator(0.0, Yaw, 0.0), LotCentre), FVector(-RowDepth * 0.5, -W * 0.5, 0.0), FVector(RowDepth * 0.5, W * 0.5, 0.0), RammsPCG::SubSeed(Seed, 900 + LotId));
					Lots.SetInt(l, RammsPCG::LotId, LotId++);
					Lots.SetInt(l, RammsPCG::BlockId, BlockId);
					Lots.Set(l, RammsPCG::Width, W);
					Lots.Set(l, RammsPCG::Depth, RowDepth);
					Lots.Set(l, RammsPCG::Setback, RammsPCG::RandRange(Rng, S->SetbackMin, S->SetbackMax));
					Lots.SetInt(l, RammsPCG::Side, Row == 0 ? 0 : 2);
					(void)FaceSign;
					x += W;
				}
			}
		}
	}
	Lots.Emit(Context, RammsPCG::PinLots);
	Parks.Emit(Context, RammsPCG::PinParks);
	return true;
}

// --- Building Massing ------------------------------------------------------------------

TArray<FPCGPinProperties> UPCGRammsBuildingMassingSettings::InputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace_GetRef(RammsPCG::PinIn, EPCGDataType::Point, true, true, LOCTEXT("MassingIn", "Lots from Subdivide Lots")).SetRequiredPin();
	return Pins;
}

TArray<FPCGPinProperties> UPCGRammsBuildingMassingSettings::OutputPinProperties() const
{
	TArray<FPCGPinProperties> Pins;
	Pins.Emplace(RammsPCG::PinPrimitives, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinPieces, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinProps, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinGrass, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinModules, EPCGDataType::Point);
	Pins.Emplace(RammsPCG::PinFeatures, EPCGDataType::Point);
	return Pins;
}

FPCGElementPtr UPCGRammsBuildingMassingSettings::CreateElement() const
{
	return MakeShared<FPCGRammsBuildingMassingElement>();
}

bool FPCGRammsBuildingMassingElement::ExecuteInternal(FPCGContext* Context) const
{
	const UPCGRammsBuildingMassingSettings* S = Context->GetInputSettings<UPCGRammsBuildingMassingSettings>();
	check(S);
	const int32 Seed = Context->GetSeed();
	const URammsWorldPalette* Palette = RammsPCG::LoadPalette(S->Palette, Context);
	const FString MatFacade = RammsPCG::Mat(Palette, RammsPaletteSlots::MatFacade);
	const FString MatFacadeAlt = RammsPCG::Mat(Palette, RammsPaletteSlots::MatFacadeAlt);
	const FString MatGlass = RammsPCG::Mat(Palette, RammsPaletteSlots::MatGlass);
	const FString MatConcrete = RammsPCG::Mat(Palette, RammsPaletteSlots::MatConcrete);
	const FString MatDoor = RammsPCG::Mat(Palette, RammsPaletteSlots::MatDoor);
	const FString MatMetal = RammsPCG::Mat(Palette, RammsPaletteSlots::MatMetal);
	const FString MatTrim = RammsPCG::Mat(Palette, RammsPaletteSlots::MatTrim);
	const FString MatRoof = RammsPCG::Mat(Palette, RammsPaletteSlots::MatRoof);
	const FString MatStorefront = RammsPCG::Mat(Palette, RammsPaletteSlots::MatStorefront);

	FRammsPointWriter Primitives, Pieces, Props, Modules, Features, Grass;
	int32 Counter = 0;
	auto NextSeed = [&]() { return RammsPCG::SubSeed(Seed, 2000 + (++Counter)); };

	for (const FPCGTaggedData& Tagged : Context->InputData.GetInputsByPin(RammsPCG::PinIn))
	{
		FPointReader R(Cast<UPCGBasePointData>(Tagged.Data));
		for (int32 i = 0; i < R.Num; ++i)
		{
			const int32 LotId = static_cast<int32>(R.GetD(i, RammsPCG::LotId, i));
			const int32 BlockIdV = static_cast<int32>(R.GetD(i, RammsPCG::BlockId, 0));
			FRandomStream Rng(RammsPCG::SubSeed(Seed, 3000 + LotId));
			const FTransform& Xf = R.T(i);
			const FVector Size = R.Size(i);           // X = depth (toward street), Y = width
			const double Depth = Size.X, Width = Size.Y;
			const double Setback = FMath::Clamp(R.GetD(i, RammsPCG::Setback, 0.0), 0.0, Depth * 0.6);
			const double Z0 = Xf.GetLocation().Z;
			const double Yaw = Xf.Rotator().Yaw;
			auto ToWorld = [&](double lx, double ly, double lz) { return Xf.TransformPosition(FVector(lx, ly, lz - Z0)); };

			double BW = FMath::Clamp(Width * FMath::Clamp(S->LotCoverage, 0.2, 1.0), 300.0, Width);
			const double FrontX = Depth * 0.5 - Setback;
			// Buildings sit at the front of the lot and are never much deeper than they are wide, so the
			// windowed facade is the long face on the street; the back of a deep lot stays open.
			double BackX = FMath::Max(-Depth * 0.5 + Depth * 0.08, FrontX - FMath::Max(BW * 1.3, 600.0));
			double BD = FMath::Max(FrontX - BackX, 300.0);
			const int32 Floors = FMath::Max(1, Rng.RandRange(FMath::Min(S->FloorsMin, S->FloorsMax), FMath::Max(S->FloorsMin, S->FloorsMax)));
			const double FH = FMath::Max(S->FloorHeight, 250.0);
			double H = Floors * FH;

			// Shell, roof and the dressing that keeps it from reading as a box: a storefront band on the
			// ground floor of taller buildings, a trim band at every floor line, a cornice and a parapet.
			const bool bHouse = S->FloorsMax <= 2 && Setback > 100.0; // set-back low-rise = a house: pitched roof, no parapet
			// A whole house mesh from the palette when one fits the lot: it replaces the shell, roof,
			// windows and dressing; the entrance pieces (steps, ramp, door record) stay ours.
			FRammsPaletteMesh HouseMesh;
			bool bHouseMesh = false;
			if (bHouse && Palette)
			{
				// Every house that fits the lot (allowing a slight scale-down) is a candidate; one is picked at random.
				if (const TArray<FRammsPaletteMesh>* Houses = Palette->GetMeshes(RammsPaletteSlots::House))
				{
					TArray<FRammsPaletteMesh> Fits;
					for (const FRammsPaletteMesh& Hm : *Houses)
					{
						const double Need = FMath::Max(Hm.Footprint.Y / FMath::Max(Width - 150.0, 1.0), Hm.Footprint.X / FMath::Max(Depth - Setback - 200.0, 1.0));
						if (Need <= 1.0) { Fits.Add(Hm); }
						else if (Need <= 1.35)
						{
							FRammsPaletteMesh Scaled = Hm;
							const double K = 1.0 / Need;
							Scaled.Scale *= K; Scaled.Footprint *= K; Scaled.Height *= K; Scaled.LocationOffset *= K;
							Scaled.EntranceOffsetY *= K; Scaled.EntranceRise *= K; Scaled.GarageDoor *= K; Scaled.GarageWidth *= K;
							Fits.Add(Scaled);
						}
					}
					if (Fits.Num() > 0) { HouseMesh = Fits[Rng.RandRange(0, Fits.Num() - 1)]; bHouseMesh = true; }
				}
			}
			if (bHouseMesh)
			{
				// Front of the house on the setback line, facing the street (+X of the lot frame). A composite
				// entry (a pack's house blueprint captured part by part) goes out as instanced modules.
				const double HD = HouseMesh.Footprint.X, HW = HouseMesh.Footprint.Y;
				const FVector HouseLoc = ToWorld(FrontX - HD * 0.5, 0.0, Z0);
				if (HouseMesh.IsComposite())
				{
					RammsPCG::WriteComposite(Modules, HouseMesh, HouseLoc, Yaw, NextSeed());
				}
				else
				{
					RammsPCG::WritePickedMesh(Props, HouseMesh, HouseLoc, Yaw, NextSeed());
				}
				const int32 h = Features.AddBox(HouseLoc + FVector(0.0, 0.0, HouseMesh.Height * 0.5), Yaw, FVector(HD, HW, HouseMesh.Height), NextSeed());
				RammsPCG::WriteManifest(Features, h, FName(TEXT("Building")), FName(TEXT("House")), true, ERammsComplianceIssue::None, HW, 0.0);
				Features.SetInt(h, RammsPCG::LotId, LotId);
			}

			// Entrance: decided before the facade so a raised ground floor can sit on its stoop.
			double EntranceY = RammsPCG::RandRange(Rng, -BW * 0.5 + 200.0, BW * 0.5 - 200.0);
			// A pack house brings its own door, porch and stairs: the entrance is where its door is.
			if (bHouseMesh) { const double HalfW = FMath::Max(HouseMesh.Footprint.Y * 0.5 - 60.0, 0.0); EntranceY = FMath::Clamp(HouseMesh.EntranceOffsetY, -HalfW, HalfW); }
			double DoorW = S->DoorClearWidth + 10.0;
			bool bDoorNarrow = false;
			if (!bHouseMesh && Rng.FRand() < S->NonCompliance * 0.5)
			{
				DoorW = RammsPCG::RandRange(Rng, FMath::Max(S->MinPassableDoorWidth, 55.0), FMath::Max(S->MinPassableDoorWidth, S->DoorClearWidth - 2.0));
				bDoorNarrow = true;
			}
			const bool bStepped = bHouseMesh ? HouseMesh.EntranceRise > 5.0 : Rng.FRand() < FMath::Clamp(S->EntranceStepChance, 0.0, 1.0);
			int32 Steps = 0; double StepRise = 0.0;
			bool bRamp = false, bRampSteep = false;
			double RampSlope = 0.0;
			if (bStepped && bHouseMesh)
			{
				// Porch stairs: no ramp, as built.
				Steps = FMath::Max(1, FMath::RoundToInt(HouseMesh.EntranceRise / 18.0));
				StepRise = HouseMesh.EntranceRise / Steps;
			}
			else if (bStepped)
			{
				Steps = Rng.RandRange(1, 3);
				StepRise = RammsPCG::RandRange(Rng, 12.0, 17.0);
				bRamp = Rng.FRand() < FMath::Clamp(S->EntranceRampChance, 0.0, 1.0);
				bRampSteep = bRamp && Rng.FRand() < S->NonCompliance;
			}
			const double EntranceRise = Steps * StepRise;
			double Threshold = 0.0;
			if (!bStepped && !bHouseMesh && Rng.FRand() < S->NonCompliance * 0.6)
			{
				Threshold = RammsPCG::RandRange(Rng, 2.0, 5.0);
			}

			// Modular facade from the palette's kit: ground floor with a door module, window floors, a
			// cornice, corner pieces, and one material pick per category for the whole building. The plan
			// snaps to the kit's 100 cm grid; the cube shell stays inside as the building's body.
			bool bModules = false, bDoorModule = false;
			FString RoofMat;
			FFacadeKit Kit;
			if (S->bFacadeModules && !bHouse && !bHouseMesh && Palette && BuildKit(Palette, S->FacadeStyles, Rng, Kit))
			{
				const double BWm = FMath::FloorToDouble(BW / 100.0) * 100.0;
				const double BDm = FMath::FloorToDouble(BD / 100.0) * 100.0;
				struct FFace { FVector2D Start, Dir, Normal; double Len, LocalYaw; TArray<double> Gf, Win, Top; int32 DoorIdx = -1; };
				TArray<FFace> Faces;
				const TArray<double> GfL = ModuleLengths(Kit.GF), WinL = ModuleLengths(Kit.Win), DoorL = ModuleLengths(Kit.GFDoor), TopL = ModuleLengths(Kit.Top);
				bool bOk = BWm >= 500.0 && BDm >= 500.0;
				if (bOk)
				{
					const double Bx = FrontX - BDm;
					Faces.Add(FFace{ FVector2D(FrontX,  BWm * 0.5), FVector2D(0.0, -1.0), FVector2D(1.0, 0.0), BWm, -90.0 });
					Faces.Add(FFace{ FVector2D(FrontX, -BWm * 0.5), FVector2D(-1.0, 0.0), FVector2D(0.0, -1.0), BDm, 180.0 });
					Faces.Add(FFace{ FVector2D(Bx, -BWm * 0.5), FVector2D(0.0, 1.0), FVector2D(-1.0, 0.0), BWm, 90.0 });
					Faces.Add(FFace{ FVector2D(Bx,  BWm * 0.5), FVector2D(1.0, 0.0), FVector2D(0.0, 1.0), BDm, 0.0 });
					for (int32 f = 0; f < Faces.Num() && bOk; ++f)
					{
						FFace& Fc = Faces[f];
						const double Fill = Fc.Len - 2.0 * CornerLen;
						for (int32 Try = 0; Try < 8; ++Try)
						{
							bOk = TileRun(Fill, GfL, Rng, Fc.Gf);
							if (!bOk || f != 0) { break; }
							TArray<int32> Cands;
							for (int32 g = 0; g < Fc.Gf.Num(); ++g) { if (DoorL.Contains(Fc.Gf[g])) { Cands.Add(g); } }
							if (Cands.Num() > 0) { Fc.DoorIdx = Cands[Rng.RandRange(0, Cands.Num() - 1)]; break; }
						}
						bOk = bOk && TileRun(Fill, WinL, Rng, Fc.Win);
						if (bOk && Kit.Top && !TileRun(Fill, TopL, Rng, Fc.Top)) { Fc.Top.Reset(); }
					}
				}
				if (bOk)
				{
					bModules = true;
					BW = BWm; BD = BDm; BackX = FrontX - BD;
					const double Rise = EntranceRise;
					const double Zb = Z0 + Rise;
					H = Rise + Kit.GFHeight + (Floors - 1) * Kit.WinHeight + Kit.TopHeight;
					const TMap<FName, FString> Mats = PickFacadeMaterials(Palette, Rng);
					// Flat roofs read as a dark membrane: the asphalt surface tiles better than the kit's roof set.
					RoofMat = RammsPCG::Mat(Palette, RammsPaletteSlots::MatAsphalt);
					auto PickAny = [&](const TArray<FRammsPaletteMesh>* Meshes, FRammsPaletteMesh& Out) -> bool
					{
						if (!Meshes || Meshes->Num() == 0) { return false; }
						Out = (*Meshes)[Rng.RandRange(0, Meshes->Num() - 1)];
						return !Out.Mesh.IsNull();
					};
					for (const FFace& Fc : Faces)
					{
						auto Place = [&](double Along, double Z)
						{
							const FVector2D P = Fc.Start + Fc.Dir * Along;
							return FTransform(FRotator(0.0, Yaw + Fc.LocalYaw, 0.0), ToWorld(P.X, P.Y, Z));
						};
						FRammsPaletteMesh M;
						// Ground floor.
						double a = CornerLen;
						for (int32 g = 0; g < Fc.Gf.Num(); ++g)
						{
							const bool bDoor = (g == Fc.DoorIdx) && PickModule(Kit.GFDoor, Fc.Gf[g], Rng, M);
							if (bDoor)
							{
								bDoorModule = true;
								EntranceY = (Fc.Start + Fc.Dir * (a + Fc.Gf[g] * 0.5)).Y;
							}
							if (bDoor || PickModule(Kit.GF, Fc.Gf[g], Rng, M)) { WriteModule(Modules, M, Place(a, Zb), Mats, NextSeed()); }
							a += Fc.Gf[g];
						}
						if (PickAny(Kit.GFCorner, M)) { WriteModule(Modules, M, Place(Fc.Len - CornerLen, Zb), Mats, NextSeed()); }
						// Window floors; the last one takes the kit's decorated top-floor variant when it has one.
						for (int32 Floor = 1; Floor < Floors; ++Floor)
						{
							const double Zf = Zb + Kit.GFHeight + (Floor - 1) * Kit.WinHeight;
							const bool bLast = Floor == Floors - 1;
							a = CornerLen;
							for (double L : Fc.Win)
							{
								if ((bLast && PickModule(Kit.WinTop, L, Rng, M)) || PickModule(Kit.Win, L, Rng, M)) { WriteModule(Modules, M, Place(a, Zf), Mats, NextSeed()); }
								a += L;
							}
							if (PickAny(Kit.WinCorner, M)) { WriteModule(Modules, M, Place(Fc.Len - CornerLen, Zf), Mats, NextSeed()); }
						}
						// Cornice / parapet.
						if (Fc.Top.Num() > 0)
						{
							const double Zt = Zb + Kit.GFHeight + (Floors - 1) * Kit.WinHeight;
							a = CornerLen;
							for (double L : Fc.Top)
							{
								if (PickModule(Kit.Top, L, Rng, M)) { WriteModule(Modules, M, Place(a, Zt), Mats, NextSeed()); }
								a += L;
							}
							if (PickAny(Kit.TopCorner, M)) { WriteModule(Modules, M, Place(Fc.Len - CornerLen, Zt), Mats, NextSeed()); }
						}
					}
					// Stoop: a raised ground floor stands on a concrete plinth under the whole facade.
					if (Rise > 0.0)
					{
						RammsPCG::WriteCube(Primitives, ToWorld((FrontX + BackX) * 0.5, 0.0, Z0 + Rise * 0.5), FVector(BD + 70.0, BW + 70.0, Rise), Yaw, MatConcrete, NextSeed());
					}
				}
			}

			const FVector ShellCentre = ToWorld((FrontX + BackX) * 0.5, 0.0, Z0 + H * 0.5);
			if (!bHouseMesh)
			{
				const double Inset = bModules ? 60.0 : 0.0;
				RammsPCG::WriteCube(Primitives, ShellCentre, FVector(BD - Inset, BW - Inset, H), Yaw, Rng.FRand() < 0.5 ? MatFacade : MatFacadeAlt, NextSeed());
			}
			if (bHouse && !bHouseMesh)
			{
				FRammsPieceDesc Rf;
				Rf.Kind = ERammsProcPieceKind::Roof;
				const bool bRidgeAlongWidth = BW >= BD;
				Rf.SizeX = (bRidgeAlongWidth ? BD : BW) + 50.0;   // span across the ridge, with eaves
				Rf.SizeY = (bRidgeAlongWidth ? BW : BD) + 30.0;   // ridge length
				Rf.SizeZ = Rf.SizeX * RammsPCG::RandRange(Rng, 0.22, 0.32);
				Rf.MaterialPath = MatRoof; Rf.MaterialPath2 = MatTrim;
				Rf.Transform = FTransform(FRotator(0.0, Yaw + (bRidgeAlongWidth ? 0.0 : 90.0), 0.0), ToWorld((FrontX + BackX) * 0.5, 0.0, Z0 + H));
				Rf.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, Rf);
			}
			else if (!bHouseMesh && bModules && !RoofMat.IsEmpty())
			{
				// A tiled roof membrane (a slab piece so the material tiles at a sensible size).
				FRammsPieceDesc Rs;
				Rs.Kind = ERammsProcPieceKind::Slab;
				Rs.SizeX = BD - 6.0; Rs.SizeY = BW - 6.0; Rs.SizeZ = 4.0;
				Rs.UVScale = 400.0;
				Rs.MaterialPath = RoofMat;
				Rs.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(BackX + 3.0, 0.0, Z0 + H + 4.0)); // slab top at its pivot
				Rs.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, Rs);
			}
			else if (!bHouseMesh)
			{
				RammsPCG::WriteCube(Primitives, ToWorld((FrontX + BackX) * 0.5, 0.0, Z0 + H + 2.0), FVector(BD - 6.0, BW - 6.0, 4.0), Yaw, MatRoof, NextSeed());
			}
			const bool bStorefront = !bModules && Floors >= 3 && Setback < 150.0 && Rng.FRand() < 0.6;
			const bool bTrim = !bHouse && !bModules && Rng.FRand() < 0.75;
			if (bTrim)
			{
				for (int32 Floor = 1; Floor < Floors; ++Floor)
				{
					RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 4.0, 0.0, Z0 + Floor * FH), FVector(8.0, BW + 8.0, 10.0), Yaw, MatTrim, NextSeed());
				}
				// Cornice.
				RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 10.0, 0.0, Z0 + H - 12.0), FVector(20.0, BW + 20.0, 24.0), Yaw, MatTrim, NextSeed());
			}
			if (!bHouse && !bModules && Floors >= 2 && Rng.FRand() < 0.7)
			{
				// Parapet around the roof edge.
				const double PT = 20.0, PH = RammsPCG::RandRange(Rng, 50.0, 90.0);
				const FString MatP = bTrim ? MatTrim : MatConcrete;
				RammsPCG::WriteCube(Primitives, ToWorld(FrontX - PT * 0.5, 0.0, Z0 + H + PH * 0.5), FVector(PT, BW, PH), Yaw, MatP, NextSeed());
				RammsPCG::WriteCube(Primitives, ToWorld(BackX + PT * 0.5, 0.0, Z0 + H + PH * 0.5), FVector(PT, BW, PH), Yaw, MatP, NextSeed());
				RammsPCG::WriteCube(Primitives, ToWorld((FrontX + BackX) * 0.5, BW * 0.5 - PT * 0.5, Z0 + H + PH * 0.5), FVector(BD, PT, PH), Yaw, MatP, NextSeed());
				RammsPCG::WriteCube(Primitives, ToWorld((FrontX + BackX) * 0.5, -BW * 0.5 + PT * 0.5, Z0 + H + PH * 0.5), FVector(BD, PT, PH), Yaw, MatP, NextSeed());
			}
			// Rooftop units on anything with a flat roof worth the name.
			if (!bHouse && BD > 500.0 && BW > 500.0)
			{
				const int32 NumUnits = Rng.RandRange(Floors >= 3 ? 1 : 0, FMath::Min(3, static_cast<int32>(BD * BW / 1.2e6)));
				for (int32 u = 0; u < NumUnits; ++u)
				{
					const FVector P = ToWorld(RammsPCG::RandRange(Rng, BackX + 150.0, FrontX - 150.0), RammsPCG::RandRange(Rng, -BW * 0.5 + 150.0, BW * 0.5 - 150.0), Z0 + H + 4.0);
					const int32 q = RammsPCG::WritePaletteMesh(Props, Palette, RammsPaletteSlots::RoofUnit, Rng, P, Yaw + Rng.RandRange(0, 3) * 90.0, NextSeed());
					if (q < 0)
					{
						RammsPCG::WriteCube(Primitives, P + FVector(0, 0, 60.0), FVector(RammsPCG::RandRange(Rng, 120.0, 220.0), RammsPCG::RandRange(Rng, 100.0, 180.0), 120.0), Yaw, MatMetal, NextSeed());
					}
				}
			}

			// Door leaf flat on the facade; its frame runs along the facade (lot Y). A facade kit's door
			// module brings its own leaf, so then only the record is written.
			if (bDoorModule || bHouseMesh)
			{
				const int32 d = Features.AddBox(ToWorld(FrontX, EntranceY, Z0 + EntranceRise + 105.0), Yaw, FVector(20.0, DoorW, 210.0), NextSeed());
				if (bDoorNarrow) { RammsPCG::WriteManifest(Features, d, FName(TEXT("Door")), FName(TEXT("Narrow")), false, ERammsComplianceIssue::DoorTooNarrow, DoorW, S->DoorClearWidth); }
				else if (Threshold > S->DoorThresholdMax) { RammsPCG::WriteManifest(Features, d, FName(TEXT("Door")), FName(TEXT("RaisedThreshold")), false, ERammsComplianceIssue::ThresholdTooHigh, Threshold, S->DoorThresholdMax); }
				else { RammsPCG::WriteManifest(Features, d, FName(TEXT("Door")), FName(TEXT("Standard")), true, ERammsComplianceIssue::None, DoorW, S->DoorClearWidth); }
				Features.SetInt(d, RammsPCG::LotId, LotId);
			}
			else
			{
				FRammsPieceDesc D;
				D.Kind = ERammsProcPieceKind::Door;
				D.SizeX = DoorW; D.SizeY = 5.0; D.SizeZ = 210.0; D.Rise = Threshold;
				D.MaterialPath = MatDoor; D.MaterialPath2 = MatMetal;
				D.ManifestKind = FName(TEXT("Door"));
				D.Transform = FTransform(FRotator(0.0, Yaw + 90.0, 0.0), ToWorld(FrontX + 3.0, EntranceY - DoorW * 0.5, Z0 + EntranceRise));
				D.Seed = NextSeed();
				if (bDoorNarrow) { D.bCompliant = false; D.Issue = ERammsComplianceIssue::DoorTooNarrow; D.ManifestSubtype = FName(TEXT("Narrow")); D.Measure = DoorW; D.Threshold = S->DoorClearWidth; }
				else if (Threshold > S->DoorThresholdMax) { D.bCompliant = false; D.Issue = ERammsComplianceIssue::ThresholdTooHigh; D.ManifestSubtype = FName(TEXT("RaisedThreshold")); D.Measure = Threshold; D.Threshold = S->DoorThresholdMax; }
				else { D.ManifestSubtype = FName(TEXT("Standard")); D.Measure = DoorW; D.Threshold = S->DoorClearWidth; }
				RammsPCG::WritePiece(Pieces, D);
			}
			const double StepsW = DoorW + 80.0;
			const double Tread = 30.0;
			if (bStepped && !bHouseMesh)
			{
				// A ramp runs along the facade beside the steps (rising toward the door, its top landing against
				// the top step), which is how entrances are retrofitted; it needs that much facade on one side
				// and a front yard at least as deep as the ramp is wide. Without the room there is no ramp.
				const double RampW = 120.0;
				const double RampSlopeV = bRampSteep ? S->RampMaxSlope * RammsPCG::RandRange(Rng, 1.4, 2.2) : S->RampMaxSlope;
				const double RampRun = EntranceRise / FMath::Max(RampSlopeV, 0.01);
				const double RampLen = RampRun + S->LandingSize;
				const double RoomPos = BW * 0.5 - (EntranceY + StepsW * 0.5) - 20.0;
				const double RoomNeg = (EntranceY - StepsW * 0.5) - (-BW * 0.5) - 20.0;
				const double FrontYard = Depth * 0.5 - FrontX;
				double RampSide = 0.0;
				if (bRamp && FrontYard >= RampW + 15.0)
				{
					if (RoomPos >= RampLen && (RoomNeg < RampLen || Rng.FRand() < 0.5)) { RampSide = 1.0; }
					else if (RoomNeg >= RampLen) { RampSide = -1.0; }
				}
				if (RampSide == 0.0) { bRamp = false; bRampSteep = false; }

				FRammsPieceDesc St;
				St.Kind = ERammsProcPieceKind::Step;
				St.StepCount = Steps; St.Rise = StepRise; St.SizeX = Tread; St.SizeY = StepsW;
				St.MaterialPath = MatConcrete;
				St.ManifestKind = FName(TEXT("Step"));
				St.Measure = EntranceRise; St.Threshold = 0.64;
				// Steps rise toward their local -X: the origin (bottom step) on the street side, the top step
				// against the facade.
				St.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(FrontX + Steps * Tread, EntranceY, Z0));
				St.bCompliant = bRamp && !bRampSteep; // steps are fine when a usable ramp exists beside them
				St.Issue = St.bCompliant ? ERammsComplianceIssue::None : ERammsComplianceIssue::StepAtEntrance;
				St.ManifestSubtype = bRamp ? FName(TEXT("WithRamp")) : FName(TEXT("NoRamp"));
				St.Seed = NextSeed();
				RammsPCG::WritePiece(Pieces, St);
				if (bRamp)
				{
					FRammsPieceDesc Rp;
					Rp.Kind = ERammsProcPieceKind::Ramp;
					Rp.Rise = EntranceRise;
					Rp.Slope = RampSlopeV;
					RampSlope = Rp.Slope;
					Rp.SizeY = RampW;
					Rp.LandingSize = S->LandingSize;
					Rp.MaterialPath = MatConcrete; Rp.MaterialPath2 = MatMetal;
					Rp.ManifestKind = FName(TEXT("Ramp"));
					Rp.Measure = Rp.Slope; Rp.Threshold = S->RampMaxSlope;
					Rp.bCompliant = !bRampSteep;
					Rp.Issue = bRampSteep ? ERammsComplianceIssue::SlopeTooSteep : ERammsComplianceIssue::None;
					Rp.ManifestSubtype = bRampSteep ? FName(TEXT("TooSteep")) : FName(TEXT("Standard"));
					// The ramp rises toward its local -X; local +X points away from the steps along the facade.
					const double LowY = EntranceY + RampSide * (StepsW * 0.5 + RampLen);
					Rp.Transform = FTransform(FRotator(0.0, Yaw + RampSide * 90.0, 0.0), ToWorld(FrontX + RampW * 0.5 + 6.0, LowY, Z0));
					Rp.Seed = NextSeed();
					RammsPCG::WritePiece(Pieces, Rp);
				}
			}
			// Entrance summary for the manifest.
			{
				const int32 f = Features.AddBox(ToWorld(FrontX, EntranceY, Z0), Yaw, FVector(60.0, StepsW, 10.0), NextSeed());
				const bool bAccessible = !bDoorNarrow && Threshold <= S->DoorThresholdMax && (!bStepped || (bRamp && !bRampSteep));
				const FName Subtype = !bStepped ? FName(TEXT("Level")) : (bRamp ? (bRampSteep ? FName(TEXT("SteppedSteepRamp")) : FName(TEXT("SteppedWithRamp"))) : FName(TEXT("SteppedNoRamp")));
				// Measure / threshold describe the issue that was reported (a compliant entrance reports its rise).
				ERammsComplianceIssue Issue = ERammsComplianceIssue::None;
				double Measure = EntranceRise, Limit = 0.0;
				if (bDoorNarrow) { Issue = ERammsComplianceIssue::DoorTooNarrow; Measure = DoorW; Limit = S->DoorClearWidth; }
				else if (Threshold > S->DoorThresholdMax) { Issue = ERammsComplianceIssue::ThresholdTooHigh; Measure = Threshold; Limit = S->DoorThresholdMax; }
				else if (bStepped && !bRamp) { Issue = ERammsComplianceIssue::StepAtEntrance; Measure = EntranceRise; Limit = S->VerticalChangeMax; }
				else if (bRampSteep) { Issue = ERammsComplianceIssue::SlopeTooSteep; Measure = RampSlope; Limit = S->RampMaxSlope; }
				RammsPCG::WriteManifest(Features, f, FName(TEXT("Entrance")), Subtype, bAccessible, Issue, Measure, Limit);
				Features.SetInt(f, RammsPCG::LotId, LotId);
			}

			// Rear car park: rows of striped stalls across the open ground behind the building, cars in most.
			if (!bHouse && S->RearParkingChance > 0.0 && Rng.FRand() < FMath::Clamp(S->RearParkingChance, 0.0, 1.0))
			{
				const double StallW = 270.0, StallD = 520.0, AisleW = 650.0;
				const double X0 = -Depth * 0.5 + 120.0, X1 = BackX - 180.0;
				const double Y0 = -Width * 0.5 + 60.0, Y1 = Width * 0.5 - 60.0;
				const FString MatLine = RammsPCG::Mat(Palette, RammsPaletteSlots::MatMarking);
				// Row 1 against the back of the lot; row 2 faces it across the drive aisle when there is room.
				TArray<TPair<double, double>> Rows; // (row near-x, facing sign)
				// Deep lots repeat the module (row, aisle, row) back to back until the ground runs out.
				for (double xm = X0; xm + StallD + AisleW <= X1 && Rows.Num() < 8; xm += 2.0 * StallD + AisleW)
				{
					Rows.Add({ xm, 1.0 });
					if (xm + 2.0 * StallD + AisleW <= X1) { Rows.Add({ xm + StallD + AisleW, -1.0 }); }
				}
				const int32 NStalls = static_cast<int32>((Y1 - Y0) / StallW);
				for (const TPair<double, double>& Row : Rows)
				{
					const double xr = Row.Key, xc = xr + StallD * 0.5;
					for (int32 k = 0; k <= NStalls; ++k)
					{
						const double y = Y0 + k * StallW;
						RammsPCG::WriteCube(Primitives, ToWorld(xc, y, Z0 + 0.6), FVector(StallD - 20.0, 10.0, 1.0), Yaw, MatLine, NextSeed());
					}
					for (int32 k = 0; k < NStalls; ++k)
					{
						if (Rng.FRand() > 0.7) { continue; }
						FRammsPaletteMesh Car;
						if (!Palette || !Palette->PickMesh(RammsPaletteSlots::Car, Rng, Car) || Car.Footprint.Y > StallW - 25.0 || Car.Footprint.X > StallD) { continue; }
						const double y = Y0 + (k + 0.5) * StallW;
						// Nose in (toward the row's back edge) most of the time.
						const double yawc = Yaw + (Row.Value > 0.0 ? 180.0 : 0.0) + (Rng.FRand() < 0.2 ? 180.0 : 0.0);
						const int32 c = RammsPCG::WritePickedMesh(Props, Car, ToWorld(xc, y, Z0), yawc, NextSeed());
						RammsPCG::WriteManifest(Props, c, FName(TEXT("Vehicle")), FName(TEXT("CarPark")), true, ERammsComplianceIssue::None, 0.0, 0.0);
					}
				}
				if (Rows.Num() > 0)
				{
					const int32 f = Features.AddBox(ToWorld((X0 + X1) * 0.5, 0.0, Z0), Yaw, FVector(X1 - X0, Y1 - Y0, 10.0), NextSeed());
					RammsPCG::WriteManifest(Features, f, FName(TEXT("CarPark")), Rows.Num() > 2 ? FName(TEXT("MultiRow")) : (Rows.Num() > 1 ? FName(TEXT("DoubleRow")) : FName(TEXT("SingleRow"))), true, ERammsComplianceIssue::None, X1 - X0, 0.0);
					Features.SetInt(f, RammsPCG::LotId, LotId);
				}
			}

			// House lots: a front walk from the sidewalk to the entrance, a driveway beside the house, and a
			// hedge or fence along the front with gaps for both.
			if (bHouse)
			{
				const double LotFront = Depth * 0.5;
				const double WalkW = 120.0;
				const double WalkStart = FrontX + (bStepped && !bHouseMesh ? Steps * Tread : 0.0);
				const FString MatPath = RammsPCG::Mat(Palette, RammsPaletteSlots::MatPath);
				if (LotFront - WalkStart > 60.0)
				{
					FRammsPieceDesc Wk;
					Wk.Kind = ERammsProcPieceKind::Slab;
					Wk.SizeX = LotFront - WalkStart; Wk.SizeY = WalkW; Wk.SizeZ = 6.0;
					Wk.MaterialPath = MatPath;
					Wk.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(WalkStart, EntranceY, Z0 + 1.5));
					Wk.ManifestKind = FName(TEXT("Path")); Wk.ManifestSubtype = FName(TEXT("FrontWalk")); Wk.Measure = WalkW; Wk.Threshold = S->MinClearWidth;
					Wk.Seed = NextSeed();
					RammsPCG::WritePiece(Pieces, Wk);
				}
				// Driveway on the side of the house away from the entrance, when it fits inside the lot.
				double DrivewayLo = 1e9, DrivewayHi = -1e9;
				const double HouseHalfW = bHouseMesh ? HouseMesh.Footprint.Y * 0.5 : BW * 0.5;
				const double HouseDepth = bHouseMesh ? HouseMesh.Footprint.X : BD;
				double DW = FMath::Clamp(S->DrivewayWidth, 250.0, 500.0);
				const double DSide = EntranceY > 0.0 ? -1.0 : 1.0;
				double DCentre = DSide * (HouseHalfW + 60.0 + DW * 0.5);
				double DStart = FrontX - HouseDepth * 0.6;
				// A house with a garage door on its front gets the driveway up to that door instead.
				const bool bGarage = bHouseMesh && HouseMesh.GarageWidth > 150.0;
				if (bGarage)
				{
					DW = FMath::Max(DW, HouseMesh.GarageWidth + 40.0);
					DCentre = HouseMesh.GarageDoor.Y;
					DStart = FrontX - HouseDepth * 0.5 + HouseMesh.GarageDoor.X;
				}
				if ((bGarage || Rng.FRand() < FMath::Clamp(S->DrivewayChance, 0.0, 1.0)) && FMath::Abs(DCentre) + DW * 0.5 < Width * 0.5 - 30.0 && LotFront - DStart > 200.0)
				{
					FRammsPieceDesc Dv;
					Dv.Kind = ERammsProcPieceKind::Slab;
					Dv.SizeX = LotFront - DStart; Dv.SizeY = DW; Dv.SizeZ = 8.0;
					Dv.MaterialPath = MatConcrete;
					Dv.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(DStart, DCentre, Z0 + 2.0));
					Dv.ManifestKind = FName(TEXT("Driveway")); Dv.ManifestSubtype = FName(TEXT("Concrete")); Dv.Measure = DW;
					Dv.Seed = NextSeed();
					RammsPCG::WritePiece(Pieces, Dv);
					DrivewayLo = DCentre - DW * 0.5; DrivewayHi = DCentre + DW * 0.5;
					// A car on it, nose to the house.
					FRammsPaletteMesh Car;
					if (Rng.FRand() < 0.55 && Palette && Palette->PickMesh(RammsPaletteSlots::Car, Rng, Car) && Car.Footprint.Y < DW - 40.0 && (!bGarage || DStart + Car.Footprint.X + 90.0 < LotFront))
					{
						const double cx = bGarage ? DStart + Car.Footprint.X * 0.5 + 90.0 : FMath::Max(DStart + Car.Footprint.X * 0.5 + 60.0, FrontX - Car.Footprint.X * 0.3);
						const int32 c = RammsPCG::WritePickedMesh(Props, Car, ToWorld(cx, DCentre, Z0 + 2.0 + 8.0 * 0.0), Yaw + (Rng.FRand() < 0.8 ? 180.0 : 0.0), NextSeed());
						RammsPCG::WriteManifest(Props, c, FName(TEXT("Vehicle")), FName(TEXT("Driveway")), true, ERammsComplianceIssue::None, 0.0, 0.0);
					}
				}
				// Front boundary: hedge (most of the time) or fence, segments end to end with gaps.
				if (Palette && Rng.FRand() < FMath::Clamp(S->FrontBoundaryChance, 0.0, 1.0))
				{
					const FName Slot = Rng.FRand() < 0.65 ? RammsPaletteSlots::Hedge : RammsPaletteSlots::Fence;
					FRammsPaletteMesh Seg;
					if (Palette->PickMesh(Slot, Rng, Seg) && Seg.Footprint.Y > 50.0)
					{
						const double SegL = Seg.Footprint.Y, Inset = 45.0 + Seg.Footprint.X * 0.5;
						const double WalkLo = EntranceY - WalkW * 0.5 - 40.0, WalkHi = EntranceY + WalkW * 0.5 + 40.0;
						for (double y = -Width * 0.5 + 40.0; y + SegL <= Width * 0.5 - 40.0; y += SegL)
						{
							const double y0 = y, y1 = y + SegL;
							if ((y1 > WalkLo && y0 < WalkHi) || (y1 > DrivewayLo - 30.0 && y0 < DrivewayHi + 30.0)) { continue; }
							RammsPCG::WritePickedMesh(Props, Seg, ToWorld(LotFront - Inset, (y0 + y1) * 0.5, Z0), Yaw, NextSeed());
						}
					}
				}
				// Back yard: a fence along the rear lot line and one side line (the neighbour's lot supplies the
				// other side), from behind the house to the back, so deep lots read as private yards.
				if (Palette && Rng.FRand() < 0.7)
				{
					FRammsPaletteMesh Seg;
					const double YardFront = FrontX - HouseDepth - 120.0;
					if (Palette->PickMesh(RammsPaletteSlots::Fence, Rng, Seg) && Seg.Footprint.Y > 50.0 && YardFront - (-Depth * 0.5) > 400.0)
					{
						const double SegL = Seg.Footprint.Y, Inset = 20.0 + Seg.Footprint.X * 0.5;
						const double RearX = -Depth * 0.5 + Inset;
						for (double y = -Width * 0.5 + 20.0; y + SegL <= Width * 0.5 - 20.0; y += SegL)
						{
							RammsPCG::WritePickedMesh(Props, Seg, ToWorld(RearX, y + SegL * 0.5, Z0), Yaw, NextSeed());
						}
						const double SideY = -Width * 0.5 + Inset;
						for (double x = RearX + 20.0; x + SegL <= YardFront; x += SegL)
						{
							RammsPCG::WritePickedMesh(Props, Seg, ToWorld(x + SegL * 0.5, SideY, Z0), Yaw + 90.0, NextSeed());
						}
					}
				}
				// The entrance's footprint in front of the facade: steps and (when there is one) the ramp along it.
				const double EntranceClear = StepsW * 0.5 + 40.0 + (bRamp ? EntranceRise / FMath::Max(S->RampMaxSlope, 0.01) + S->LandingSize : 0.0);
				// Foundation planting: a row of shrubs along the front of the house on both sides of the entrance,
				// clear of the steps, ramp, walk and driveway.
				if (Palette && Rng.FRand() < 0.85)
				{
					FRammsPaletteMesh Sh;
					if (Palette->PickMesh(RammsPaletteSlots::FoundationShrub, Rng, Sh) || Palette->PickMesh(RammsPaletteSlots::Shrub, Rng, Sh))
					{
						const double Sp = FMath::Max(FMath::Max(Sh.Footprint.X, Sh.Footprint.Y), 50.0) + 25.0;
						const double Xs = FrontX + FMath::Max(Sh.Footprint.X, 50.0) * 0.5 + 20.0;
						if (Xs < LotFront - 150.0)
						{
							for (double y = -HouseHalfW + Sp * 0.5; y <= HouseHalfW - Sp * 0.5; y += Sp)
							{
								if (FMath::Abs(y - EntranceY) < EntranceClear || (y > DrivewayLo - 40.0 && y < DrivewayHi + 40.0) || Rng.FRand() < 0.12) { continue; }
								FRammsPaletteMesh Pick = Sh;
								if (Rng.FRand() < 0.3) { Palette->PickMesh(RammsPaletteSlots::FoundationShrub, Rng, Pick); }
								const int32 p = RammsPCG::WritePickedMesh(Props, Pick, ToWorld(Xs, y, Z0), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), RammsPCG::RandRange(Rng, 0.8, 1.15));
								RammsPCG::WriteManifest(Props, p, FName(TEXT("Shrub")), FName(TEXT("Foundation")), true, ERammsComplianceIssue::None, 0.0, 0.0);
							}
						}
					}
				}
				// Flowers beside the walk.
				if (Palette && Rng.FRand() < 0.5 && LotFront - FrontX > 400.0)
				{
					const double Fy = EntranceY + (Rng.FRand() < 0.5 ? -1.0 : 1.0) * (WalkW * 0.5 + 60.0);
					if (!(Fy > DrivewayLo - 60.0 && Fy < DrivewayHi + 60.0))
					{
						RammsPCG::WritePaletteMesh(Props, Palette, RammsPaletteSlots::Flowers, Rng, ToWorld(FrontX + (LotFront - FrontX) * RammsPCG::RandRange(Rng, 0.35, 0.7), Fy, Z0), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed());
					}
				}
				// Mailbox on its post at the street end of the walk (or the driveway).
				if (Palette && Rng.FRand() < 0.8)
				{
					const double My = DrivewayHi > DrivewayLo ? (DCentre > EntranceY ? DrivewayLo - 45.0 : DrivewayHi + 45.0) : EntranceY + (WalkW * 0.5 + 45.0);
					const int32 m = RammsPCG::WritePaletteMesh(Props, Palette, RammsPaletteSlots::Mailbox, Rng, ToWorld(LotFront - 35.0, My, Z0), Yaw, NextSeed());
					RammsPCG::WriteManifest(Props, m, FName(TEXT("Prop")), FName(TEXT("Mailbox")), true, ERammsComplianceIssue::None, 0.0, 0.0);
				}
				// The driveway carries on across the sidewalk (and planting strip) to the curb as an apron.
				if (DrivewayHi > DrivewayLo && S->SidewalkWidth > 1.0)
				{
					FRammsPieceDesc Ap;
					Ap.Kind = ERammsProcPieceKind::Slab;
					Ap.SizeX = S->SidewalkWidth; Ap.SizeY = DrivewayHi - DrivewayLo; Ap.SizeZ = 3.0;
					Ap.MaterialPath = MatConcrete;
					Ap.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(LotFront, (DrivewayLo + DrivewayHi) * 0.5, Z0 + 0.5));
					Ap.Seed = NextSeed();
					RammsPCG::WritePiece(Pieces, Ap);
				}
				// Yard terrain: gentle grassy rises in the back yard and, in a deep front yard, a low one on the side
				// away from the walk and driveway, so lawns are not billiard-table flat. Clear of the house, walk,
				// driveway, fences and foundation planting; the grass below follows them (YardZ).
				struct FYardMound { FVector2D C; double SX, SY, Hm; };
				TArray<FYardMound> YardMounds;
				if (S->TerrainVariation > 0.0)
				{
					auto AddMound = [&](double X0, double X1, double Y0, double Y1, double HLo, double HHi)
					{
						if (X1 - X0 < 260.0 || Y1 - Y0 < 260.0) { return; }
						const double SX = RammsPCG::RandRange(Rng, 0.6, 1.0) * (X1 - X0), SY = RammsPCG::RandRange(Rng, 0.6, 1.0) * (Y1 - Y0);
						const FVector2D C(RammsPCG::RandRange(Rng, X0 + SX * 0.5, X1 - SX * 0.5), RammsPCG::RandRange(Rng, Y0 + SY * 0.5, Y1 - SY * 0.5));
						const double Hm = FMath::Min(RammsPCG::RandRange(Rng, HLo, HHi) * S->TerrainVariation, FMath::Min(SX, SY) * 0.12);
						YardMounds.Add({ C, SX, SY, Hm });
						FRammsPieceDesc Mn;
						Mn.Kind = ERammsProcPieceKind::Mound;
						Mn.SizeX = SX; Mn.SizeY = SY; Mn.Rise = Hm; Mn.UVScale = 300.0;
						Mn.MaterialPath = RammsPCG::Mat(Palette, RammsPaletteSlots::MatLawn);
						Mn.ManifestKind = FName(TEXT("Terrain")); Mn.ManifestSubtype = FName(TEXT("Mound"));
						Mn.Measure = Hm * PI / FMath::Min(SX, SY);
						Mn.Transform = FTransform(FRotator(0.0, Yaw, 0.0), ToWorld(C.X, C.Y, Z0));
						Mn.Seed = NextSeed();
						RammsPCG::WritePiece(Pieces, Mn);
					};
					const double BX0 = -Depth * 0.5 + 130.0, BX1 = FrontX - HouseDepth - 160.0;
					const int32 NBack = (BX1 - BX0) * (Width - 260.0) > 900.0 * 900.0 ? 2 : 1;
					for (int32 k = 0; k < NBack; ++k)
					{
						const double YSpan = (Width - 260.0) / NBack;
						AddMound(BX0, BX1, -Width * 0.5 + 130.0 + YSpan * k, -Width * 0.5 + 130.0 + YSpan * (k + 1), 20.0, 55.0);
					}
					const double Away = -DSide; // the side of the walk away from the driveway
					const double FY0 = EntranceY + Away * (WalkW * 0.5 + 90.0), FY1 = Away * (Width * 0.5 - 90.0);
					AddMound(FrontX + 190.0, LotFront - 110.0, FMath::Min(FY0, FY1), FMath::Max(FY0, FY1), 12.0, 30.0);
				}
				auto YardZ = [&](const FVector2D& P)
				{
					double Z = Z0;
					for (const FYardMound& Mn : YardMounds)
					{
						const double E = FMath::Sqrt(FMath::Square(2.0 * (P.X - Mn.C.X) / Mn.SX) + FMath::Square(2.0 * (P.Y - Mn.C.Y) / Mn.SY));
						if (E < 1.0) { Z = FMath::Max(Z, Z0 + Mn.Hm * 0.5 * (1.0 + FMath::Cos(PI * E)) - 2.0); }
					}
					return Z;
				};
				// Grass clumps over the yard (sparser behind the house), off the house, walk, entrance and driveway.
				if (S->GrassDensity > 0.0 && Palette && Palette->HasSlot(RammsPaletteSlots::GrassClump))
				{
					const double Step = 100.0 / FMath::Sqrt(FMath::Max(S->GrassDensity, 0.05));
					const FBox2D NoGrass[4] = {
						FBox2D(FVector2D(FrontX - HouseDepth - 30.0, -HouseHalfW - 30.0), FVector2D(FrontX + 30.0, HouseHalfW + 30.0)),
						FBox2D(FVector2D(WalkStart - 10.0, EntranceY - WalkW * 0.5 - 15.0), FVector2D(LotFront + 10.0, EntranceY + WalkW * 0.5 + 15.0)),
						FBox2D(FVector2D(DStart - 10.0, DrivewayLo - 15.0), FVector2D(LotFront + 10.0, DrivewayHi + 15.0)),
						FBox2D(FVector2D(FrontX - 10.0, EntranceY - EntranceClear), FVector2D(FrontX + 260.0, EntranceY + EntranceClear)) };
					for (double gx = -Depth * 0.5 + 30.0; gx < LotFront - 30.0; gx += Step)
					{
						const bool bBack = gx < FrontX - HouseDepth;
						for (double gy = -Width * 0.5 + 30.0; gy < Width * 0.5 - 30.0; gy += Step)
						{
							if (bBack && Rng.FRand() < 0.45) { continue; }
							const FVector2D P(gx + RammsPCG::RandRange(Rng, -Step * 0.45, Step * 0.45), gy + RammsPCG::RandRange(Rng, -Step * 0.45, Step * 0.45));
							bool bOut = false;
							for (const FBox2D& B : NoGrass) { if (B.bIsValid && B.IsInside(P)) { bOut = true; break; } }
							if (bOut) { continue; }
							FRammsPaletteMesh G; if (!Palette->PickMesh(RammsPaletteSlots::GrassClump, Rng, G)) { break; }
							RammsPCG::WritePickedMesh(Grass, G, ToWorld(P.X, P.Y, YardZ(P)), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), RammsPCG::RandRange(Rng, 0.7, 1.3));
						}
					}
					// Short tufts, dense, over the whole yard: the lawn reads as grass, not a green texture.
					if (Palette->HasSlot(RammsPaletteSlots::LawnTuft))
					{
						// Front and back yard alike: the grass spawner culls it with distance and gives it no collision.
						const double TStep = 50.0 / FMath::Sqrt(FMath::Max(S->GrassDensity, 0.05));
						for (double gx = -Depth * 0.5 + 20.0; gx < LotFront - 20.0; gx += TStep)
						{
							for (double gy = -Width * 0.5 + 20.0; gy < Width * 0.5 - 20.0; gy += TStep)
							{
								const FVector2D P(gx + RammsPCG::RandRange(Rng, -TStep * 0.5, TStep * 0.5), gy + RammsPCG::RandRange(Rng, -TStep * 0.5, TStep * 0.5));
								bool bOut = false;
								for (const FBox2D& B : NoGrass) { if (B.bIsValid && B.IsInside(P)) { bOut = true; break; } }
								if (bOut) { continue; }
								FRammsPaletteMesh G; if (!Palette->PickMesh(RammsPaletteSlots::LawnTuft, Rng, G)) { break; }
								RammsPCG::WritePickedMesh(Grass, G, ToWorld(P.X, P.Y, YardZ(P)), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), RammsPCG::RandRange(Rng, 0.45, 0.9));
							}
						}
					}
				}
				// The planting strip in front of the lot (between the walk and the curb): street trees spaced along it
				// and a street light, both clear of the driveway apron, plus grass. Canopy streets get big old trees.
				const double FZs = FMath::Min(S->FurnitureZoneWidth, S->SidewalkWidth);
				if (S->PlantingStrip > 0.5 && FZs > 60.0 && Palette)
				{
					const double StripX = LotFront + S->SidewalkWidth - FZs * 0.5;
					FRandomStream BlockRng(RammsPCG::SubSeed(Seed, 9100 + BlockIdV));
					const bool bCanopy = BlockRng.FRand() < FMath::Clamp(S->CanopyChance, 0.0, 1.0);
					auto ClearOfDrive = [&](double Yc, double Half) { return !(Yc + Half > DrivewayLo - 60.0 && Yc - Half < DrivewayHi + 60.0); };
					if (S->TreeSpacing > 200.0)
					{
						const double Sp = bCanopy ? FMath::Max(S->TreeSpacing * 0.65, 500.0) : S->TreeSpacing;
						const int32 NT = FMath::Max(1, FMath::RoundToInt(Width / Sp));
						for (int32 k = 0; k < NT; ++k)
						{
							const double Ty = -Width * 0.5 + Width * (k + 0.5) / NT + RammsPCG::RandRange(Rng, -60.0, 60.0);
							if (!ClearOfDrive(Ty, 90.0) || FMath::Abs(Ty) > Width * 0.5 - 80.0) { continue; }
							FRammsPaletteMesh Tm;
							if (bCanopy ? (Palette->PickMesh(RammsPaletteSlots::TreeLarge, Rng, Tm) || Palette->PickMesh(RammsPaletteSlots::Tree, Rng, Tm)) : Palette->PickMesh(RammsPaletteSlots::Tree, Rng, Tm))
							{
								const int32 t = RammsPCG::WritePickedMesh(Props, Tm, ToWorld(StripX, Ty, Z0), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(),
									bCanopy ? RammsPCG::RandRange(Rng, 1.1, 1.4) : RammsPCG::RandRange(Rng, 0.85, 1.1));
								RammsPCG::WriteManifest(Props, t, FName(TEXT("Tree")), bCanopy ? FName(TEXT("Canopy")) : FName(TEXT("StreetTree")), true, ERammsComplianceIssue::None, 0.0, 0.0);
							}
						}
					}
					if (S->StreetLightSpacing > 300.0 && (LotId % FMath::Max(1, FMath::RoundToInt(S->StreetLightSpacing / FMath::Max(Width, 100.0)))) == 0)
					{
						const double Ly = (LotId % 2 == 0 ? -1.0 : 1.0) * (Width * 0.5 - 70.0);
						if (ClearOfDrive(Ly, 40.0))
						{
							const int32 l = RammsPCG::WritePaletteMesh(Props, Palette, RammsPaletteSlots::StreetLight, Rng, ToWorld(StripX, Ly, Z0), Yaw + 90.0, NextSeed());
							RammsPCG::WriteManifest(Props, l, FName(TEXT("Prop")), RammsPaletteSlots::StreetLight, true, ERammsComplianceIssue::None, 0.0, 0.0);
						}
					}
					if (S->GrassDensity > 0.0 && Palette->HasSlot(RammsPaletteSlots::GrassClump))
					{
						const double Step = 100.0 / FMath::Sqrt(FMath::Max(S->GrassDensity, 0.05));
						for (double gy = -Width * 0.5 + 20.0; gy < Width * 0.5 - 20.0; gy += Step)
						{
							for (double gx = StripX - FZs * 0.5 + 25.0; gx < StripX + FZs * 0.5 - 20.0; gx += Step)
							{
								const double Py = gy + RammsPCG::RandRange(Rng, -Step * 0.4, Step * 0.4);
								if (!ClearOfDrive(Py, 30.0)) { continue; }
								FRammsPaletteMesh G; if (!Palette->PickMesh(RammsPaletteSlots::GrassClump, Rng, G)) { break; }
								RammsPCG::WritePickedMesh(Grass, G, ToWorld(FMath::Clamp(gx + RammsPCG::RandRange(Rng, -Step * 0.3, Step * 0.3), StripX - FZs * 0.5 + 20.0, StripX + FZs * 0.5 - 20.0), Py, Z0),
									RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), RammsPCG::RandRange(Rng, 0.6, 1.0));
							}
						}
					}
				}
			}

			// Yard trees in the open ground beside or behind the building (procedural stand-ins,
			// swapped for the palette's tree mesh by the spawner when one is assigned).
			if (S->YardTreeChance > 0.0 && Rng.FRand() < FMath::Clamp(S->YardTreeChance, 0.0, 1.0))
			{
				const double SideRoom = (Width - BW) * 0.5;
				const double BackRoom = BackX - (-Depth * 0.5);
				double tx = 0.0, ty = 0.0;
				bool bPlaced = false;
				if (BackRoom > 500.0)
				{
					tx = RammsPCG::RandRange(Rng, -Depth * 0.5 + 200.0, BackX - 250.0);
					ty = RammsPCG::RandRange(Rng, -Width * 0.5 + 200.0, Width * 0.5 - 200.0);
					bPlaced = true;
				}
				else if (SideRoom > 350.0)
				{
					const double Side = Rng.FRand() < 0.5 ? -1.0 : 1.0;
					tx = RammsPCG::RandRange(Rng, BackX + 100.0, FrontX - 100.0);
					ty = Side * (BW * 0.5 + SideRoom * 0.5);
					bPlaced = true;
				}
				if (bPlaced)
				{
					RammsPCG::WriteFoliage(Props, Pieces, Palette, Rng.FRand() < 0.5 ? RammsPaletteSlots::TreeSmall : RammsPaletteSlots::Tree, Rng,
						ToWorld(tx, ty, Z0), RammsPCG::RandRange(Rng, 0.0, 360.0), NextSeed(), RammsPCG::RandRange(Rng, 350.0, 650.0), RammsPCG::RandRange(Rng, 550.0, 950.0),
						RammsPCG::Mat(Palette, RammsPaletteSlots::MatFoliage), RammsPCG::Mat(Palette, RammsPaletteSlots::MatTrunk), FName(TEXT("Tree")));
				}
			}

			// Entrance canopy and a dark door surround.
			if (!bHouseMesh && !bModules) { RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 2.0, EntranceY, Z0 + EntranceRise + 110.0), FVector(4.0, DoorW + 30.0, 225.0), Yaw, MatStorefront, NextSeed()); }
			if (!bHouseMesh && !bModules && Rng.FRand() < 0.5)
			{
				RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 45.0, EntranceY, Z0 + EntranceRise + 235.0), FVector(90.0, DoorW + 90.0, 8.0), Yaw, MatStorefront, NextSeed());
			}

			// Ground floor storefront: glass between dark pilasters, a fascia above, no windows on that floor.
			if (bStorefront && !bHouseMesh)
			{
				const double Sill = 35.0, Top = FH - 45.0;
				const double PilW = 20.0;
				double y = -BW * 0.5 + 10.0;
				while (y < BW * 0.5 - 10.0)
				{
					const double Bay = FMath::Min(RammsPCG::RandRange(Rng, 220.0, 360.0), BW * 0.5 - 10.0 - y);
					const double yc = y + Bay * 0.5;
					if (FMath::Abs(yc - EntranceY) > DoorW * 0.5 + Bay * 0.5 + 10.0 && Bay > 80.0)
					{
						RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 3.0, yc, Z0 + (Sill + Top) * 0.5), FVector(6.0, Bay - PilW, Top - Sill), Yaw, MatGlass, NextSeed());
						RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 5.0, yc, Z0 + Sill * 0.5), FVector(10.0, Bay - PilW, Sill), Yaw, MatStorefront, NextSeed());
					}
					if (FMath::Abs(y + Bay - EntranceY) > DoorW * 0.5 + 25.0 && y + Bay < BW * 0.5 - 10.0)
					{
						RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 6.0, y + Bay, Z0 + Top * 0.5), FVector(12.0, PilW, Top), Yaw, MatStorefront, NextSeed());
					}
					y += Bay;
				}
				RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 8.0, 0.0, Z0 + FH - 22.0), FVector(16.0, BW + 16.0, 44.0), Yaw, MatStorefront, NextSeed());
			}

			// Windows on the front facade: glass in a dark frame with a sill.
			if (S->WindowSpacing > 50.0 && !bHouseMesh && !bModules)
			{
				const double WinW = FMath::Clamp(S->WindowSpacing * 0.45, 70.0, 140.0), WinH = FMath::Clamp(FH * 0.45, 100.0, 170.0);
				for (int32 Floor = bStorefront ? 1 : 0; Floor < Floors; ++Floor)
				{
					for (double y = -BW * 0.5 + S->WindowSpacing * 0.5; y < BW * 0.5 - 60.0; y += S->WindowSpacing)
					{
						if (Floor == 0 && FMath::Abs(y - EntranceY) < DoorW * 0.5 + 100.0) { continue; }
						const double zc = Z0 + Floor * FH + FH * 0.5 + 15.0;
						RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 2.0, y, zc), FVector(4.0, WinW + 14.0, WinH + 14.0), Yaw, MatStorefront, NextSeed());
						RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 3.0, y, zc), FVector(6.0, WinW, WinH), Yaw, MatGlass, NextSeed());
						RammsPCG::WriteCube(Primitives, ToWorld(FrontX + 6.0, y, zc - WinH * 0.5 - 10.0), FVector(12.0, WinW + 20.0, 6.0), Yaw, MatTrim, NextSeed());
					}
				}
			}
		}
	}
	Primitives.Emit(Context, RammsPCG::PinPrimitives, { TEXT("Building") });
	Pieces.Emit(Context, RammsPCG::PinPieces, { TEXT("Building") });
	Props.Emit(Context, RammsPCG::PinProps, { TEXT("Building") });
	Grass.Emit(Context, RammsPCG::PinGrass, { TEXT("Grass") });
	Modules.Emit(Context, RammsPCG::PinModules, { TEXT("Building") });
	Features.Emit(Context, RammsPCG::PinFeatures);
	return true;
}

#undef LOCTEXT_NAMESPACE
