// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "PCGSettings.h"
#include "PCGElement.h"
#include "Helpers/PCGHelpers.h"
#include "RammsWorldGenTypes.h"
#include "RammsWorldPalette.h"
#include "RammsPCGCommon.generated.h"

class UPCGBasePointData;
class UPCGSplineData;
class UPCGParamData;
struct FPCGContext;
struct FSplinePoint;

/**
 * Everything the custom nodes share: attribute names, a point writer that
 * isolates the 5.8 point-data API to one place, piece/primitive emitters, and
 * a settings base class with the properties every node needs.
 *
 * Attribute names match ARammsProcPiece's properties exactly, so a Spawn Actor
 * node with one override per property reproduces a piece from a point, and the
 * manifest node reads the same names off mesh-spawned features.
 */
namespace RammsPCG
{
	// spawner inputs
	inline const FName Mesh(TEXT("Mesh"));
	inline const FName Material(TEXT("Material"));
	/** Facade modules override every material slot: attributes Material0..Material{N-1}, index = slot. */
	constexpr int32 NumModuleMaterials = 8;
	inline FName ModuleMaterial(int32 Slot) { return FName(*FString::Printf(TEXT("Material%d"), Slot)); }
	// ARammsProcPiece properties
	inline const FName KindId(TEXT("KindId"));
	inline const FName SizeX(TEXT("SizeX"));
	inline const FName SizeY(TEXT("SizeY"));
	inline const FName SizeZ(TEXT("SizeZ"));
	inline const FName Rise(TEXT("Rise"));
	inline const FName Slope(TEXT("Slope"));
	inline const FName FlareSlope(TEXT("FlareSlope"));
	inline const FName StepCount(TEXT("StepCount"));
	inline const FName OpeningWidth(TEXT("OpeningWidth"));
	inline const FName OpeningOffset(TEXT("OpeningOffset"));
	inline const FName OpeningHeight(TEXT("OpeningHeight"));
	inline const FName LandingSize(TEXT("LandingSize"));
	inline const FName WarningDepth(TEXT("WarningDepth"));
	inline const FName MaterialPath(TEXT("MaterialPath"));
	inline const FName MaterialPath2(TEXT("MaterialPath2"));
	inline const FName MaterialPath3(TEXT("MaterialPath3"));
	inline const FName Openings(TEXT("Openings"));
	inline const FName UVScale(TEXT("UVScale"));
	// manifest (on pieces and on mesh features alike)
	inline const FName ManifestKind(TEXT("ManifestKind"));
	inline const FName ManifestSubtype(TEXT("ManifestSubtype"));
	inline const FName bCompliant(TEXT("bCompliant"));
	inline const FName IssueId(TEXT("IssueId"));
	inline const FName Measure(TEXT("Measure"));
	inline const FName Threshold(TEXT("Threshold"));
	// structure
	inline const FName BlockId(TEXT("BlockId"));
	inline const FName LotId(TEXT("LotId"));
	inline const FName RoomId(TEXT("RoomId"));
	inline const FName RoomKind(TEXT("RoomKind"));
	inline const FName Side(TEXT("Side"));
	inline const FName Length(TEXT("Length"));
	inline const FName Width(TEXT("Width"));
	inline const FName Depth(TEXT("Depth"));
	inline const FName Setback(TEXT("Setback"));
	inline const FName RouteWidth(TEXT("RouteWidth"));
	inline const FName FurnitureZone(TEXT("FurnitureZone"));
	inline const FName ClearWidth(TEXT("ClearWidth"));
	inline const FName IsPark(TEXT("IsPark"));
	inline const FName RouteName(TEXT("RouteName"));
	inline const FName SegmentIndex(TEXT("SegmentIndex")); // consecutive route points with one RouteName form a polyline
	inline const FName Json(TEXT("Json"));

	// pins
	inline const FName PinIn(TEXT("In"));
	inline const FName PinOut(TEXT("Out"));
	inline const FName PinPrimitives(TEXT("Primitives"));
	inline const FName PinProps(TEXT("Props"));
	inline const FName PinPieces(TEXT("Pieces"));
	inline const FName PinModules(TEXT("Modules"));
	inline const FName PinRoads(TEXT("Roads"));
	inline const FName PinSidewalks(TEXT("Sidewalks"));
	inline const FName PinBlocks(TEXT("Blocks"));
	inline const FName PinLots(TEXT("Lots"));
	inline const FName PinParks(TEXT("Parks"));
	inline const FName PinRoutes(TEXT("Routes"));
	inline const FName PinFeatures(TEXT("Features"));
	inline const FName PinRooms(TEXT("Rooms"));

	inline const TCHAR* CubeMesh = TEXT("/Engine/BasicShapes/Cube.Cube");
	inline const TCHAR* CylinderMesh = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
	inline const TCHAR* DefaultMaterial = TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial");

	// Uniform random in [0,1) from a stream; FRandomStream is const-friendly.
	inline double Rand01(const FRandomStream& R) { return R.FRand(); }
	inline bool Chance(const FRandomStream& R, double P) { return R.FRand() < P; }
	// Double-safe uniform range (FRandomStream::FRandRange is float-only).
	inline double RandRange(const FRandomStream& R, double Min, double Max) { return Min + (Max - Min) * static_cast<double>(R.FRand()); }
	// Box-Muller normal.
	double RandNormal(const FRandomStream& R, double Mean, double Std);
	// Deterministic per-feature sub-seed.
	inline int32 SubSeed(int32 Seed, int32 A, int32 B = 0) { return PCGHelpers::ComputeSeed(Seed, A, B); }
}

/**
 * Accumulates points and typed attributes, then writes a UPCGBasePointData in
 * one go. Every node emits through this so the point-data API lives here only.
 */
struct RAMMSWORLDGEN_API FRammsPointWriter
{
	struct FPt
	{
		FTransform Transform;
		FVector BoundsMin = FVector(-50.0);
		FVector BoundsMax = FVector(50.0);
		int32 Seed = 0;
		float Density = 1.f;
	};
	TArray<FPt> Points;

	int32 Add(const FTransform& Transform, const FVector& BoundsMin, const FVector& BoundsMax, int32 Seed, float Density = 1.f);
	/** Convenience: a point at Location with yaw, whose bounds span Size centred on the point. */
	int32 AddBox(const FVector& Location, double YawDeg, const FVector& Size, int32 Seed);

	void Set(int32 Index, FName Attr, double Value);
	void SetInt(int32 Index, FName Attr, int32 Value);
	void Set(int32 Index, FName Attr, const FString& Value);
	void Set(int32 Index, FName Attr, FName Value);
	void SetBool(int32 Index, FName Attr, bool Value);
	void SetPath(int32 Index, FName Attr, const FSoftObjectPath& Value);
	void Set(int32 Index, FName Attr, const FVector& Value);

	int32 Num() const { return Points.Num(); }
	bool IsEmpty() const { return Points.Num() == 0; }

	/** Create the point data (null when empty). */
	UPCGBasePointData* Build(FPCGContext* Context) const;
	/** Build and append to the context output on Pin; no-op when empty. */
	void Emit(FPCGContext* Context, FName Pin, const TArray<FString>& Tags = {}) const;

private:
	template <typename T> void SetT(TMap<FName, TArray<T>>& Map, int32 Index, FName Attr, const T& Value, const T& Default);
	TMap<FName, TArray<double>> Doubles;
	TMap<FName, TArray<int32>> Ints;
	TMap<FName, TArray<FString>> Strings;
	TMap<FName, TArray<FName>> Names;
	TMap<FName, TArray<bool>> Bools;
	TMap<FName, TArray<FSoftObjectPath>> Paths;
	TMap<FName, TArray<FVector>> Vectors;
};

/** A procedural piece to be spawned by Spawn Actor(ARammsProcPiece). */
struct RAMMSWORLDGEN_API FRammsPieceDesc
{
	ERammsProcPieceKind Kind = ERammsProcPieceKind::Slab;
	FTransform Transform;
	double SizeX = 100.0, SizeY = 100.0, SizeZ = 10.0;
	double Rise = 0.0, Slope = 0.0833, FlareSlope = 0.1;
	int32 StepCount = 1;
	double OpeningWidth = 0.0, OpeningOffset = 0.0, OpeningHeight = 210.0;
	double LandingSize = 152.4, WarningDepth = 0.0;
	double UVScale = 200.0;
	FString MaterialPath, MaterialPath2, MaterialPath3;
	/** Walls: extra openings, "offset,width,sill,head;..." (see ARammsProcPiece::Openings). */
	FString Openings;
	FName ManifestKind, ManifestSubtype;
	bool bCompliant = true;
	ERammsComplianceIssue Issue = ERammsComplianceIssue::None;
	double Measure = 0.0, Threshold = 0.0;
	int32 Seed = 0;
};

namespace RammsPCG
{
	/** Append a piece point with every ARammsProcPiece property as an attribute. */
	RAMMSWORLDGEN_API int32 WritePiece(FRammsPointWriter& W, const FRammsPieceDesc& P);

	/** Append a scaled unit cube instance: Centre is the box centre; yaw in degrees. */
	RAMMSWORLDGEN_API int32 WriteCube(FRammsPointWriter& W, const FVector& Centre, const FVector& Size, double YawDeg, const FString& MaterialPath, int32 Seed);

	/** Append a palette mesh instance standing on Location (base at Z). Returns -1 when the slot is empty. */
	RAMMSWORLDGEN_API int32 WritePaletteMesh(FRammsPointWriter& W, const URammsWorldPalette* Palette, FName Slot, const FRandomStream& Rng, const FVector& Location, double YawDeg, int32 Seed, FRammsPaletteMesh* OutPicked = nullptr);
	/** Write an already-chosen palette mesh (so a node can measure the mesh it will actually spawn). ScaleMul varies the instance. */
	RAMMSWORLDGEN_API int32 WritePickedMesh(FRammsPointWriter& W, const FRammsPaletteMesh& Picked, const FVector& Location, double YawDeg, int32 Seed, double ScaleMul = 1.0);

	/** A composite palette entry (a house built from parts): one Modules point per part, with the
	 *  entry's placement applied and the parts' own materials as Material0..7. Returns the part count. */
	RAMMSWORLDGEN_API int32 WriteComposite(FRammsPointWriter& Modules, const FRammsPaletteMesh& Picked, const FVector& Location, double YawDeg, int32 Seed);

	/**
	 * A tree or shrub: the palette's mesh for Slot when it has one (with a little random size
	 * variation), else a procedural piece of the given size. Either way a manifest feature of ManifestKind.
	 */
	RAMMSWORLDGEN_API void WriteFoliage(FRammsPointWriter& Props, FRammsPointWriter& Pieces, const URammsWorldPalette* Palette, FName Slot,
		const FRandomStream& Rng, const FVector& Location, double YawDeg, int32 Seed, double ProcSizeX, double ProcSizeZ,
		const FString& MatFoliage, const FString& MatTrunk, FName InManifestKind);

	/** Manifest attributes on an already-added point (mesh features). */
	RAMMSWORLDGEN_API void WriteManifest(FRammsPointWriter& W, int32 Index, FName Kind, FName Subtype, bool bCompliant, ERammsComplianceIssue Issue, double Measure, double Threshold);

	/** First spatial input's world bounds, or a box of Size centred on the origin when there is none. */
	RAMMSWORLDGEN_API FBox InputBounds(FPCGContext* Context, FName Pin, const FVector& FallbackSize);

	/** Emit one spline (open polyline) on Pin. */
	RAMMSWORLDGEN_API void EmitSpline(FPCGContext* Context, FName Pin, const TArray<FVector>& Points, bool bClosed, const TArray<FString>& Tags = {});

	/** Emit a single-entry attribute set with one string attribute. */
	RAMMSWORLDGEN_API void EmitStringParam(FPCGContext* Context, FName Pin, FName Attr, const FString& Value);

	/** Load the palette (main thread). Logs once per node when missing. */
	RAMMSWORLDGEN_API const URammsWorldPalette* LoadPalette(const TSoftObjectPtr<URammsWorldPalette>& Palette, const FPCGContext* Context);

	/** Material path for a slot with the engine fallback. */
	RAMMSWORLDGEN_API FString Mat(const URammsWorldPalette* Palette, FName Slot);
}

/**
 * Base for every Ramms node: the palette and the compliance dial, both
 * overridable from the generator's Params attribute set.
 */
UCLASS(Abstract)
class RAMMSWORLDGEN_API URammsPCGSettingsBase : public UPCGSettings
{
	GENERATED_BODY()

public:
	URammsPCGSettingsBase();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ramms", meta = (PCG_Overridable))
	TSoftObjectPtr<URammsWorldPalette> Palette;

	/** Probability (0..1) that any individual feature is generated non-compliant. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ramms", meta = (PCG_Overridable, ClampMin = 0, ClampMax = 1))
	double NonCompliance = 0.15;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ramms|Accessibility", meta = (PCG_Overridable))
	double MinClearWidth = 91.4;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ramms|Accessibility", meta = (PCG_Overridable))
	double PreferredClearWidth = 152.4;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ramms|Accessibility", meta = (PCG_Overridable))
	double RampMaxSlope = 0.0833;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Ramms|Accessibility", meta = (PCG_Overridable))
	double LandingSize = 152.4;

	//~ UPCGSettings
	virtual bool UseSeed() const override { return true; }
#if WITH_EDITOR
	virtual EPCGSettingsType GetType() const override { return EPCGSettingsType::Spatial; }
	virtual FText GetNodeTooltipText() const override;
#endif
};

/** Base element: main-thread only (palettes are loaded synchronously), never cached across seeds. */
class RAMMSWORLDGEN_API FRammsPCGElementBase : public IPCGElement
{
public:
	virtual bool CanExecuteOnlyOnMainThread(FPCGContext* Context) const override { return true; }
	virtual bool IsCacheable(const UPCGSettings* InSettings) const override { return false; }
};
