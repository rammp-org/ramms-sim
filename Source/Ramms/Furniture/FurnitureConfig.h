// Copyright Ramms. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "FurnitureConfig.generated.h"

/**
 * Describes a single drawer slot in a furniture piece.
 */
USTRUCT(BlueprintType)
struct FFurnitureDrawerConfig
{
	GENERATED_BODY()

	/** Height of this drawer in cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawer", meta = (ClampMin = "5.0"))
	float Height = 15.0f;

	/** How far the drawer can slide out in cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawer", meta = (ClampMin = "1.0"))
	float MaxTravel = 30.0f;

	/** Mass of the drawer in kg */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawer|Physics", meta = (ClampMin = "0.1"))
	float Mass = 2.0f;

	/** Linear damping applied to the drawer slide */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawer|Physics", meta = (ClampMin = "0.0"))
	float LinearDamping = 5.0f;

	/** Spring stiffness that pulls the drawer back to closed position (0 = no spring) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawer|Physics", meta = (ClampMin = "0.0"))
	float SpringStiffness = 0.0f;

	/** Spring damping for the return spring */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawer|Physics", meta = (ClampMin = "0.0"))
	float SpringDamping = 1.0f;

	/** Optional material override for the drawer face */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawer|Material")
	TSoftObjectPtr<UMaterialInterface> DrawerFaceMaterial;

	/** Optional material override for the drawer interior */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawer|Material")
	TSoftObjectPtr<UMaterialInterface> DrawerInteriorMaterial;
};

/**
 * Describes a single door on a furniture piece.
 */
USTRUCT(BlueprintType)
struct FFurnitureDoorConfig
{
	GENERATED_BODY()

	/** Width of the door in cm (0 = auto-fill remaining width) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Door", meta = (ClampMin = "0.0"))
	float Width = 0.0f;

	/** Maximum angle the door can open in degrees */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Door", meta = (ClampMin = "1.0", ClampMax = "170.0"))
	float MaxOpenAngle = 110.0f;

	/** If true, door hinges on the right side; otherwise left */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Door")
	bool bHingeOnRight = false;

	/** Mass of the door in kg */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Door|Physics", meta = (ClampMin = "0.1"))
	float Mass = 3.0f;

	/** Angular damping on the hinge */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Door|Physics", meta = (ClampMin = "0.0"))
	float AngularDamping = 2.0f;

	/** Spring stiffness that pulls the door back to closed position (0 = no spring) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Door|Physics", meta = (ClampMin = "0.0"))
	float SpringStiffness = 0.0f;

	/** Spring damping for the return spring */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Door|Physics", meta = (ClampMin = "0.0"))
	float SpringDamping = 1.0f;

	/** Optional material override for the door face */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Door|Material")
	TSoftObjectPtr<UMaterialInterface> DoorFaceMaterial;
};

/**
 * Data asset that fully describes a procedural furniture piece.
 * Create instances in the Content Browser (Miscellaneous > Data Asset > FurnitureConfig)
 * to define presets like "Kitchen Cabinet", "Dresser", "Filing Cabinet", etc.
 */
UCLASS(BlueprintType)
class RAMMS_API UFurnitureConfig : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	// ---- Dimensions ----

	/** Overall cabinet width in cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Dimensions", meta = (ClampMin = "10.0"))
	float CabinetWidth = 60.0f;

	/** Overall cabinet height in cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Dimensions", meta = (ClampMin = "10.0"))
	float CabinetHeight = 80.0f;

	/** Overall cabinet depth in cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Dimensions", meta = (ClampMin = "10.0"))
	float CabinetDepth = 45.0f;

	/** Thickness of the cabinet walls, top, bottom, and shelves in cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Dimensions", meta = (ClampMin = "0.5", ClampMax = "10.0"))
	float WallThickness = 2.0f;

	// ---- Body Physics ----

	/** Mass of the cabinet body in kg */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body|Physics", meta = (ClampMin = "1.0"))
	float BodyMass = 25.0f;

	/** If true, the cabinet body simulates physics. If false, it is static/kinematic. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body|Physics")
	bool bBodySimulatesPhysics = false;

	// ---- Drawers ----

	/** Configuration for each drawer, from top to bottom.
	 *  Leave empty for no drawers. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Drawers")
	TArray<FFurnitureDrawerConfig> Drawers;

	// ---- Doors ----

	/** Configuration for each door, from left to right.
	 *  Doors occupy the remaining height below any drawers.
	 *  Leave empty for no doors. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Doors")
	TArray<FFurnitureDoorConfig> Doors;

	// ---- Materials ----

	/** Material for the cabinet exterior (sides, top, bottom, back) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Materials")
	TSoftObjectPtr<UMaterialInterface> ExteriorMaterial;

	/** Material for the cabinet interior surfaces */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Materials")
	TSoftObjectPtr<UMaterialInterface> InteriorMaterial;

	// ---- Utility ----

	/** Display name for this preset (shown in editor UI) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Meta")
	FText DisplayName;

	/** Helper: total height consumed by all drawers */
	UFUNCTION(BlueprintPure, Category = "Furniture")
	float GetTotalDrawerHeight() const;

	/** Helper: remaining height available for doors */
	UFUNCTION(BlueprintPure, Category = "Furniture")
	float GetDoorZoneHeight() const;
};
