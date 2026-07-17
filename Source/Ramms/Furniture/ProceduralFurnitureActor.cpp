// Copyright Ramms. All Rights Reserved.

#include "Furniture/ProceduralFurnitureActor.h"
#include "Furniture/FurnitureGeneratorComponent.h"
#include "Furniture/FurnitureConfig.h"

AProceduralFurnitureActor::AProceduralFurnitureActor()
{
	PrimaryActorTick.bCanEverTick = false;

	SceneRoot = CreateDefaultSubobject<USceneComponent>(TEXT("SceneRoot"));
	SetRootComponent(SceneRoot);

	FurnitureGenerator = CreateDefaultSubobject<UFurnitureGeneratorComponent>(TEXT("FurnitureGenerator"));
}

void AProceduralFurnitureActor::SetConfigAndRegenerate(UFurnitureConfig* NewConfig)
{
	if (FurnitureGenerator)
	{
		FurnitureGenerator->Config = NewConfig;
		FurnitureGenerator->GenerateFurniture();
	}
}

void AProceduralFurnitureActor::Regenerate()
{
	if (FurnitureGenerator)
	{
		FurnitureGenerator->GenerateFurniture();
	}
}
