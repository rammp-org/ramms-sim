// Copyright Ramms. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FurnitureGeneratorComponent.generated.h"

class UFurnitureConfig;
class UStaticMeshComponent;
class UPhysicsConstraintComponent;
class UStaticMesh;
class UMaterialInterface;

/**
 * Tracks a spawned drawer: its mesh, constraint, and config index.
 */
USTRUCT(BlueprintType)
struct FFurnitureDrawerRuntime
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture")
	TObjectPtr<UStaticMeshComponent> MeshComp = nullptr;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture")
	TObjectPtr<UPhysicsConstraintComponent> Constraint = nullptr;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture")
	int32 ConfigIndex = INDEX_NONE;
};

/**
 * Tracks a spawned door: its mesh, constraint, and config index.
 */
USTRUCT(BlueprintType)
struct FFurnitureDoorRuntime
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture")
	TObjectPtr<UStaticMeshComponent> MeshComp = nullptr;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture")
	TObjectPtr<UPhysicsConstraintComponent> Constraint = nullptr;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture")
	int32 ConfigIndex = INDEX_NONE;
};

/**
 * Component that procedurally generates furniture geometry from a UFurnitureConfig.
 *
 * Attach this to any Actor. Call GenerateFurniture() (or set bGenerateOnBeginPlay)
 * and the component will spawn:
 *   - A static body mesh (the cabinet shell)
 *   - Drawer meshes with prismatic (sliding) physics constraints
 *   - Door meshes with hinge (twist) physics constraints
 *
 * All physics parameters (mass, damping, spring, limits) come from the config.
 */
UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class RAMMS_API UFurnitureGeneratorComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UFurnitureGeneratorComponent();

	// ---- Configuration ----

	/** The furniture preset to generate */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Furniture")
	TObjectPtr<UFurnitureConfig> Config;

	/** If true, furniture is generated in BeginPlay automatically */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Furniture")
	bool bGenerateOnBeginPlay = true;

	// ---- Runtime State ----

	/** The cabinet body mesh */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture|Runtime")
	TObjectPtr<UStaticMeshComponent> BodyMesh;

	/** All spawned drawer instances */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture|Runtime")
	TArray<FFurnitureDrawerRuntime> RuntimeDrawers;

	/** All spawned door instances */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture|Runtime")
	TArray<FFurnitureDoorRuntime> RuntimeDoors;

	// ---- API ----

	/** Generate (or regenerate) all furniture geometry from the current Config. */
	UFUNCTION(BlueprintCallable, Category = "Furniture")
	void GenerateFurniture();

	/** Destroy all previously generated components. */
	UFUNCTION(BlueprintCallable, Category = "Furniture")
	void ClearFurniture();

protected:
	virtual void BeginPlay() override;

private:
	/** Cube mesh used for all parts (scaled to size) */
	UPROPERTY()
	TObjectPtr<UStaticMesh> CubeMesh;

	void LoadCubeMesh();

	UStaticMeshComponent* CreateBoxComponent(
		const FName&		Name,
		USceneComponent*	Parent,
		const FVector&		RelativeLocation,
		const FVector&		Scale,
		UMaterialInterface* Material,
		float				Mass,
		bool				bSimulatePhysics);

	UPhysicsConstraintComponent* CreatePrismaticConstraint(
		const FName&		  Name,
		USceneComponent*	  Parent,
		UStaticMeshComponent* BodyComp,
		UStaticMeshComponent* MovableComp,
		const FVector&		  RelativeLocation,
		float				  LinearLimit,
		float				  SpringStiffness,
		float				  SpringDamping);

	UPhysicsConstraintComponent* CreateHingeConstraint(
		const FName&		  Name,
		USceneComponent*	  Parent,
		UStaticMeshComponent* BodyComp,
		UStaticMeshComponent* DoorComp,
		const FVector&		  RelativeLocation,
		float				  MaxAngle,
		float				  SpringStiffness,
		float				  SpringDamping,
		bool				  bHingeOnRight);

	void SpawnBody();
	void SpawnDrawers();
	void SpawnDoors();

	UMaterialInterface* ResolveMaterial(const TSoftObjectPtr<UMaterialInterface>& SoftPtr) const;
};
