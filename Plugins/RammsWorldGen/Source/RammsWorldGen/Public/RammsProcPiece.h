// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "RammsWorldGenTypes.h"
#include "RammsProcPiece.generated.h"

class UDynamicMeshComponent;
class UDecalComponent;
class UDynamicMesh;
class UMaterialInterface;

/**
 * A dimension-driven procedural piece: the geometry whose exact size decides
 * whether a wheelchair can use it. Curb ramps, curbs, steps, ramps, walls with
 * door openings, door leaves, bollards, planters, and low-poly trees.
 *
 * PCG's Spawn Actor node spawns it with every property below mapped from
 * point attributes of the same name, then calls Rebuild() (listed in the
 * node's post-spawn functions), so the mesh reflects the overridden values.
 * Hand-placed copies rebuild from OnConstruction.
 *
 * Conventions: the actor origin is at the piece's base on the ground, pieces
 * extend along +X, and every size is in cm. See ERammsProcPieceKind for how
 * each kind reads the dimensions.
 */
UCLASS(BlueprintType, Blueprintable, ClassGroup = (Ramms), meta = (DisplayName = "Ramms Procedural Piece"))
class RAMMSWORLDGEN_API ARammsProcPiece : public AActor
{
	GENERATED_BODY()

public:
	ARammsProcPiece();

	// --- shape -----------------------------------------------------------------
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece")
	ERammsProcPieceKind Kind = ERammsProcPieceKind::Slab;

	/** PCG writes the kind as an integer here; when >= 0 it takes precedence over Kind. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece", AdvancedDisplay)
	int32 KindId = -1;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double SizeX = 100.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double SizeY = 100.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double SizeZ = 10.0;
	/** Curb height, step rise, ramp total rise, door threshold height. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double Rise = 15.0;
	/** Running slope, rise over run. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double Slope = 0.0833;
	/** Flare slope for curb ramps, rise over run. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double FlareSlope = 0.1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") int32 StepCount = 1;
	/** Wall door opening width; 0 = solid wall. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double OpeningWidth = 0.0;
	/** Centre of the opening along the wall, measured from the wall start. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double OpeningOffset = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double OpeningHeight = 210.0;
	/** Walls: extra openings as "offset,width,sill,head;..." (cm along the wall from its start, sill and head
	 *  heights above the base). Each gets a frame (material 2) and, when its sill is above the floor, a glass
	 *  pane (material 3): windows. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") FString Openings;
	/** Level landing length at the top of a ramp. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double LandingSize = 152.4;
	/** Detectable warning strip at the bottom of a curb ramp (depth, cm); 0 = none. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece") double WarningDepth = 0.0;

	// --- look ------------------------------------------------------------------
	/** Soft object path of the primary material (slot 0). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Material") FString MaterialPath;
	/** Secondary material (slot 1): trunk for trees, warning strip for curb ramps, door frame. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Material") FString MaterialPath2;
	/** Tertiary material (slot 2): window glass. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Material") FString MaterialPath3;
	/** World-space UV tiling in cm per repeat, for box-projected UVs. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Material") double UVScale = 200.0;

	// --- ground truth ------------------------------------------------------------
	/** Manifest kind this piece reports as (Hazard, CurbRamp, Entrance, Door ...). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Manifest") FName ManifestKind;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Manifest") FName ManifestSubtype;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Manifest") bool bCompliant = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Manifest") int32 IssueId = 0;
	/** The quantity the manifest reports for this piece; 0 = derive it from the geometry (door width, slope, rise...). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Manifest") double Measure = 0.0;
	/** The limit that quantity was checked against (door clear width, max slope, max rise...); 0 = not checked. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Piece|Manifest") double Threshold = 0.0;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Piece")
	TObjectPtr<UDynamicMeshComponent> MeshComponent;

	/** Decal kind only: created on first rebuild as a Decal. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Piece")
	TObjectPtr<UDecalComponent> DecalComponent;

	/** Rebuild the mesh from the properties. Safe to call repeatedly. */
	UFUNCTION(BlueprintCallable, CallInEditor, Category = "Ramms|WorldGen")
	void Rebuild();

	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen")
	ERammsProcPieceKind GetEffectiveKind() const;

	/** Describe this piece for the world manifest. */
	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen")
	FRammsManifestFeature ToManifestFeature() const;

	virtual void OnConstruction(const FTransform& Transform) override;

private:
	void BuildSlab(UDynamicMesh* Mesh);
	void BuildCurb(UDynamicMesh* Mesh);
	void BuildCurbRamp(UDynamicMesh* Mesh);
	void BuildSteps(UDynamicMesh* Mesh);
	void BuildRamp(UDynamicMesh* Mesh);
	void BuildWall(UDynamicMesh* Mesh);
	void BuildDoor(UDynamicMesh* Mesh);
	void BuildBollard(UDynamicMesh* Mesh);
	void BuildTree(UDynamicMesh* Mesh);
	void BuildShrub(UDynamicMesh* Mesh);
	void BuildRoof(UDynamicMesh* Mesh);
	void BuildPlanter(UDynamicMesh* Mesh);
	void BuildColumn(UDynamicMesh* Mesh);
	void BuildMound(UDynamicMesh* Mesh);
	void BuildPatch(UDynamicMesh* Mesh);
	void BuildDecal();

	void ApplyMaterials();
	void ApplyCollision();
};
