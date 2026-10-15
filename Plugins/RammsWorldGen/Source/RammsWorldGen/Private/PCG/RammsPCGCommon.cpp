// Copyright ATDev. All Rights Reserved.
#include "PCG/RammsPCGCommon.h"

#include "PCGContext.h"
#include "PCGPin.h"
#include "Components/SplineComponent.h"
#include "Data/PCGBasePointData.h"
#include "PCGParamData.h"
#include "Data/PCGSpatialData.h"
#include "Data/PCGSplineData.h"
#include "Metadata/PCGMetadata.h"
#include "Metadata/PCGMetadataAttribute.h"
#include "RammsWorldGenModule.h"

#define LOCTEXT_NAMESPACE "RammsPCG"

double RammsPCG::RandNormal(const FRandomStream& R, double Mean, double Std)
{
	const double U1 = FMath::Max(R.FRand(), 1e-9);
	const double U2 = R.FRand();
	return Mean + Std * FMath::Sqrt(-2.0 * FMath::Loge(U1)) * FMath::Cos(2.0 * PI * U2);
}

// --- FRammsPointWriter -------------------------------------------------------------

int32 FRammsPointWriter::Add(const FTransform& Transform, const FVector& BoundsMin, const FVector& BoundsMax, int32 Seed, float Density)
{
	FPt& P = Points.AddDefaulted_GetRef();
	P.Transform = Transform;
	P.BoundsMin = BoundsMin;
	P.BoundsMax = BoundsMax;
	P.Seed = Seed;
	P.Density = Density;
	return Points.Num() - 1;
}

int32 FRammsPointWriter::AddBox(const FVector& Location, double YawDeg, const FVector& Size, int32 Seed)
{
	return Add(FTransform(FRotator(0.0, YawDeg, 0.0), Location), -Size * 0.5, Size * 0.5, Seed);
}

template <typename T>
void FRammsPointWriter::SetT(TMap<FName, TArray<T>>& Map, int32 Index, FName Attr, const T& Value, const T& Default)
{
	TArray<T>& Arr = Map.FindOrAdd(Attr);
	if (Arr.Num() < Points.Num())
	{
		const int32 Old = Arr.Num();
		Arr.SetNum(Points.Num());
		for (int32 i = Old; i < Arr.Num(); ++i) { Arr[i] = Default; }
	}
	if (Arr.IsValidIndex(Index))
	{
		Arr[Index] = Value;
	}
}

void FRammsPointWriter::Set(int32 Index, FName Attr, double Value) { SetT<double>(Doubles, Index, Attr, Value, 0.0); }
void FRammsPointWriter::SetInt(int32 Index, FName Attr, int32 Value) { SetT<int32>(Ints, Index, Attr, Value, 0); }
void FRammsPointWriter::Set(int32 Index, FName Attr, const FString& Value) { SetT<FString>(Strings, Index, Attr, Value, FString()); }
void FRammsPointWriter::Set(int32 Index, FName Attr, FName Value) { SetT<FName>(Names, Index, Attr, Value, NAME_None); }
void FRammsPointWriter::SetBool(int32 Index, FName Attr, bool Value) { SetT<bool>(Bools, Index, Attr, Value, false); }
void FRammsPointWriter::SetPath(int32 Index, FName Attr, const FSoftObjectPath& Value) { SetT<FSoftObjectPath>(Paths, Index, Attr, Value, FSoftObjectPath()); }
void FRammsPointWriter::Set(int32 Index, FName Attr, const FVector& Value) { SetT<FVector>(Vectors, Index, Attr, Value, FVector::ZeroVector); }

namespace
{
	template <typename T>
	void WriteAttributes(UPCGMetadata* Metadata, const TMap<FName, TArray<T>>& Map, const TArray<PCGMetadataEntryKey>& Keys, const T& Default)
	{
		for (const TPair<FName, TArray<T>>& Pair : Map)
		{
			FPCGMetadataAttribute<T>* Attr = Metadata->CreateAttribute<T>(Pair.Key, Default, /*bAllowsInterpolation=*/false, /*bOverrideParent=*/true);
			if (!Attr)
			{
				continue;
			}
			for (int32 i = 0; i < Keys.Num(); ++i)
			{
				Attr->SetValue(Keys[i], Pair.Value.IsValidIndex(i) ? Pair.Value[i] : Default);
			}
		}
	}
}

UPCGBasePointData* FRammsPointWriter::Build(FPCGContext* Context) const
{
	if (Points.Num() == 0 || !Context)
	{
		return nullptr;
	}
	UPCGBasePointData* Data = FPCGContext::NewPointData_AnyThread(Context);
	const int32 N = Points.Num();
	Data->SetNumPoints(N, /*bInitializeValues=*/true);
	Data->AllocateProperties(EPCGPointNativeProperties::All);

	TPCGValueRange<FTransform> Transforms = Data->GetTransformValueRange();
	TPCGValueRange<FVector> BMin = Data->GetBoundsMinValueRange();
	TPCGValueRange<FVector> BMax = Data->GetBoundsMaxValueRange();
	TPCGValueRange<int32> Seeds = Data->GetSeedValueRange();
	TPCGValueRange<float> Densities = Data->GetDensityValueRange();
	TPCGValueRange<float> Steepness = Data->GetSteepnessValueRange();
	TPCGValueRange<int64> Entries = Data->GetMetadataEntryValueRange();

	UPCGMetadata* Metadata = Data->Metadata;
	TArray<PCGMetadataEntryKey> Keys;
	Keys.Reserve(N);
	for (int32 i = 0; i < N; ++i)
	{
		Transforms[i] = Points[i].Transform;
		BMin[i] = Points[i].BoundsMin;
		BMax[i] = Points[i].BoundsMax;
		Seeds[i] = Points[i].Seed;
		Densities[i] = Points[i].Density;
		Steepness[i] = 1.f;
		const PCGMetadataEntryKey Key = Metadata->AddEntry();
		Entries[i] = Key;
		Keys.Add(Key);
	}

	WriteAttributes<double>(Metadata, Doubles, Keys, 0.0);
	WriteAttributes<int32>(Metadata, Ints, Keys, 0);
	WriteAttributes<FString>(Metadata, Strings, Keys, FString());
	WriteAttributes<FName>(Metadata, Names, Keys, NAME_None);
	WriteAttributes<bool>(Metadata, Bools, Keys, false);
	WriteAttributes<FSoftObjectPath>(Metadata, Paths, Keys, FSoftObjectPath());
	WriteAttributes<FVector>(Metadata, Vectors, Keys, FVector::ZeroVector);
	return Data;
}

void FRammsPointWriter::Emit(FPCGContext* Context, FName Pin, const TArray<FString>& Tags) const
{
	UPCGBasePointData* Data = Build(Context);
	if (!Data)
	{
		return;
	}
	FPCGTaggedData& Out = Context->OutputData.TaggedData.Emplace_GetRef();
	Out.Data = Data;
	Out.Pin = Pin;
	for (const FString& T : Tags) { Out.Tags.Add(T); }
}

// --- emitters --------------------------------------------------------------------------

int32 RammsPCG::WritePiece(FRammsPointWriter& W, const FRammsPieceDesc& P)
{
	const int32 i = W.Add(P.Transform, FVector(0.0, -P.SizeY * 0.5, 0.0), FVector(P.SizeX, P.SizeY * 0.5, P.SizeZ), P.Seed);
	W.SetInt(i, KindId, static_cast<int32>(P.Kind));
	W.Set(i, SizeX, P.SizeX);
	W.Set(i, SizeY, P.SizeY);
	W.Set(i, SizeZ, P.SizeZ);
	W.Set(i, Rise, P.Rise);
	W.Set(i, Slope, P.Slope);
	W.Set(i, FlareSlope, P.FlareSlope);
	W.SetInt(i, StepCount, P.StepCount);
	W.Set(i, OpeningWidth, P.OpeningWidth);
	W.Set(i, OpeningOffset, P.OpeningOffset);
	W.Set(i, OpeningHeight, P.OpeningHeight);
	W.Set(i, LandingSize, P.LandingSize);
	W.Set(i, WarningDepth, P.WarningDepth);
	W.Set(i, UVScale, P.UVScale);
	W.Set(i, MaterialPath, P.MaterialPath);
	W.Set(i, MaterialPath2, P.MaterialPath2);
	W.Set(i, MaterialPath3, P.MaterialPath3);
	W.Set(i, Openings, P.Openings);
	W.Set(i, ManifestKind, P.ManifestKind);
	W.Set(i, ManifestSubtype, P.ManifestSubtype);
	W.SetBool(i, bCompliant, P.bCompliant);
	W.SetInt(i, IssueId, static_cast<int32>(P.Issue));
	W.Set(i, Measure, P.Measure);
	W.Set(i, Threshold, P.Threshold);
	return i;
}

int32 RammsPCG::WriteCube(FRammsPointWriter& W, const FVector& Centre, const FVector& Size, double YawDeg, const FString& InMaterial, int32 Seed)
{
	const FVector Scale(FMath::Max(Size.X, 0.1) / 100.0, FMath::Max(Size.Y, 0.1) / 100.0, FMath::Max(Size.Z, 0.1) / 100.0);
	const int32 i = W.Add(FTransform(FRotator(0.0, YawDeg, 0.0), Centre, Scale), FVector(-50.0), FVector(50.0), Seed);
	W.SetPath(i, Mesh, FSoftObjectPath(CubeMesh));
	W.SetPath(i, Material, FSoftObjectPath(InMaterial.IsEmpty() ? FString(DefaultMaterial) : InMaterial));
	return i;
}

int32 RammsPCG::WritePaletteMesh(FRammsPointWriter& W, const URammsWorldPalette* Palette, FName Slot, const FRandomStream& Rng, const FVector& Location, double YawDeg, int32 Seed, FRammsPaletteMesh* OutPicked)
{
	FRammsPaletteMesh Picked;
	if (!Palette || !Palette->PickMesh(Slot, Rng, Picked))
	{
		return -1;
	}
	if (OutPicked)
	{
		*OutPicked = Picked;
	}
	return WritePickedMesh(W, Picked, Location, YawDeg, Seed);
}

int32 RammsPCG::WritePickedMesh(FRammsPointWriter& W, const FRammsPaletteMesh& Picked, const FVector& Location, double YawDeg, int32 Seed, double ScaleMul)
{
	const FRotator Rot = (FRotator(0.0, YawDeg, 0.0).Quaternion() * Picked.RotationOffset.Quaternion()).Rotator();
	const FVector Loc = Location + FRotator(0.0, YawDeg, 0.0).RotateVector(Picked.LocationOffset * ScaleMul);
	const FVector Half(Picked.Footprint.X * 0.5 * ScaleMul, Picked.Footprint.Y * 0.5 * ScaleMul, Picked.Height * 0.5 * ScaleMul);
	const int32 i = W.Add(FTransform(Rot, Loc, FVector(Picked.Scale * ScaleMul)), FVector(-Half.X, -Half.Y, 0.0), FVector(Half.X, Half.Y, Picked.Height * ScaleMul), Seed);
	W.SetPath(i, Mesh, Picked.Mesh.ToSoftObjectPath());
	return i;
}

int32 RammsPCG::WriteComposite(FRammsPointWriter& Modules, const FRammsPaletteMesh& Picked, const FVector& Location, double YawDeg, int32 Seed)
{
	const FRotator Rot = (FRotator(0.0, YawDeg, 0.0).Quaternion() * Picked.RotationOffset.Quaternion()).Rotator();
	const FVector Loc = Location + FRotator(0.0, YawDeg, 0.0).RotateVector(Picked.LocationOffset);
	const FTransform Pivot(Rot, Loc, FVector(Picked.Scale));
	int32 n = 0;
	for (const FRammsPalettePart& Part : Picked.Parts)
	{
		if (Part.Mesh.IsNull()) { continue; }
		const FTransform Xf = Part.RelativeTransform * Pivot;
		const int32 i = Modules.Add(Xf, FVector(-50.0), FVector(50.0), SubSeed(Seed, n));
		Modules.SetPath(i, Mesh, Part.Mesh.ToSoftObjectPath());
		for (int32 s = 0; s < NumModuleMaterials; ++s)
		{
			Modules.SetPath(i, ModuleMaterial(s), Part.Materials.IsValidIndex(s) ? Part.Materials[s].ToSoftObjectPath() : FSoftObjectPath());
		}
		++n;
	}
	return n;
}

void RammsPCG::WriteFoliage(FRammsPointWriter& Props, FRammsPointWriter& Pieces, const URammsWorldPalette* Palette, FName Slot,
	const FRandomStream& Rng, const FVector& Location, double YawDeg, int32 Seed, double ProcSizeX, double ProcSizeZ,
	const FString& MatFoliage, const FString& MatTrunk, FName InManifestKind)
{
	FRammsPaletteMesh M;
	if (Palette && Palette->PickMesh(Slot, Rng, M))
	{
		const int32 p = WritePickedMesh(Props, M, Location, YawDeg, Seed, RandRange(Rng, 0.85, 1.15));
		WriteManifest(Props, p, InManifestKind, Slot, true, ERammsComplianceIssue::None, 0.0, 0.0);
		return;
	}
	FRammsPieceDesc T;
	T.Kind = (Slot == RammsPaletteSlots::Shrub || Slot == RammsPaletteSlots::Hedge) ? ERammsProcPieceKind::Shrub : ERammsProcPieceKind::Tree;
	T.SizeX = ProcSizeX;
	T.SizeZ = ProcSizeZ;
	T.MaterialPath = MatFoliage; T.MaterialPath2 = MatTrunk;
	T.ManifestKind = InManifestKind;
	T.Transform = FTransform(FRotator(0.0, YawDeg, 0.0), Location);
	T.Seed = Seed;
	WritePiece(Pieces, T);
}

void RammsPCG::WriteManifest(FRammsPointWriter& W, int32 Index, FName Kind, FName Subtype, bool bInCompliant, ERammsComplianceIssue Issue, double InMeasure, double InThreshold)
{
	if (Index < 0)
	{
		return;
	}
	W.Set(Index, ManifestKind, Kind);
	W.Set(Index, ManifestSubtype, Subtype);
	W.SetBool(Index, bCompliant, bInCompliant);
	W.SetInt(Index, IssueId, static_cast<int32>(Issue));
	W.Set(Index, Measure, InMeasure);
	W.Set(Index, Threshold, InThreshold);
}

FBox RammsPCG::InputBounds(FPCGContext* Context, FName Pin, const FVector& FallbackSize)
{
	if (Context)
	{
		const TArray<FPCGTaggedData> Inputs = Context->InputData.GetInputsByPin(Pin);
		for (const FPCGTaggedData& Tagged : Inputs)
		{
			if (const UPCGSpatialData* Spatial = Cast<UPCGSpatialData>(Tagged.Data))
			{
				const FBox B = Spatial->GetBounds();
				if (B.IsValid && B.GetSize().X > 1.0 && B.GetSize().Y > 1.0)
				{
					return B;
				}
			}
		}
	}
	return FBox(-FallbackSize * 0.5, FallbackSize * 0.5);
}

void RammsPCG::EmitSpline(FPCGContext* Context, FName Pin, const TArray<FVector>& Points, bool bClosed, const TArray<FString>& Tags)
{
	if (!Context || Points.Num() < 2)
	{
		return;
	}
	TArray<FSplinePoint> SplinePoints;
	SplinePoints.Reserve(Points.Num());
	for (int32 i = 0; i < Points.Num(); ++i)
	{
		SplinePoints.Emplace(static_cast<float>(i), Points[i], ESplinePointType::Linear);
	}
	UPCGSplineData* Spline = FPCGContext::NewObject_AnyThread<UPCGSplineData>(Context);
	Spline->Initialize(SplinePoints, bClosed, FTransform::Identity);
	FPCGTaggedData& Out = Context->OutputData.TaggedData.Emplace_GetRef();
	Out.Data = Spline;
	Out.Pin = Pin;
	for (const FString& T : Tags) { Out.Tags.Add(T); }
}

void RammsPCG::EmitStringParam(FPCGContext* Context, FName Pin, FName Attr, const FString& Value)
{
	if (!Context)
	{
		return;
	}
	UPCGParamData* Param = FPCGContext::NewObject_AnyThread<UPCGParamData>(Context);
	FPCGMetadataAttribute<FString>* A = Param->Metadata->CreateAttribute<FString>(Attr, FString(), false, true);
	const PCGMetadataEntryKey Key = Param->Metadata->AddEntry();
	if (A)
	{
		A->SetValue(Key, Value);
	}
	FPCGTaggedData& Out = Context->OutputData.TaggedData.Emplace_GetRef();
	Out.Data = Param;
	Out.Pin = Pin;
}

const URammsWorldPalette* RammsPCG::LoadPalette(const TSoftObjectPtr<URammsWorldPalette>& Palette, const FPCGContext* Context)
{
	if (Palette.IsNull())
	{
		UE_LOG(LogRammsWorldGen, Warning, TEXT("Ramms PCG node has no palette; meshes will be skipped and materials fall back to the engine default"));
		return nullptr;
	}
	const URammsWorldPalette* P = Palette.LoadSynchronous();
	if (!P)
	{
		UE_LOG(LogRammsWorldGen, Warning, TEXT("Ramms PCG node could not load palette %s"), *Palette.ToString());
	}
	return P;
}

FString RammsPCG::Mat(const URammsWorldPalette* Palette, FName Slot)
{
	if (Palette)
	{
		const FString M = Palette->MaterialPath(Slot);
		if (!M.IsEmpty())
		{
			return M;
		}
	}
	return FString(DefaultMaterial);
}

// --- settings base -------------------------------------------------------------------------

URammsPCGSettingsBase::URammsPCGSettingsBase()
{
	bEnabled = true;
}

#if WITH_EDITOR
FText URammsPCGSettingsBase::GetNodeTooltipText() const
{
	return LOCTEXT("BaseTooltip", "Ramms world generation node. Wire the generator's Params attribute set into the Overrides pin.");
}
#endif

#undef LOCTEXT_NAMESPACE
