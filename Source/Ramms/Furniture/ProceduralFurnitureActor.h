// Copyright Ramms. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ProceduralFurnitureActor.generated.h"

class UFurnitureGeneratorComponent;
class UFurnitureConfig;

/**
 * A ready-to-place actor that procedurally generates furniture from a config.
 *
 * Usage:
 *   1. Place in level
 *   2. Assign a UFurnitureConfig to the FurnitureGenerator component
 *   3. Furniture spawns on BeginPlay (or call Regenerate from BP)
 *
 * The actor has a SceneComponent root so all generated meshes
 * and constraints are properly hierarchical.
 */
UCLASS(BlueprintType, Blueprintable)
class RAMMS_API AProceduralFurnitureActor : public AActor
{
	GENERATED_BODY()

public:
	AProceduralFurnitureActor();

	/** The generator component — configure the FurnitureConfig here */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture")
	TObjectPtr<UFurnitureGeneratorComponent> FurnitureGenerator;

	/** Quick-access: set the config and regenerate in one call */
	UFUNCTION(BlueprintCallable, Category = "Furniture")
	void SetConfigAndRegenerate(UFurnitureConfig* NewConfig);

	/** Regenerate furniture with the current config */
	UFUNCTION(BlueprintCallable, CallInEditor, Category = "Furniture")
	void Regenerate();

protected:
	/** Root scene component */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Furniture")
	TObjectPtr<USceneComponent> SceneRoot;
};
