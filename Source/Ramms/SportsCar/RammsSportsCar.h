// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "RammsPawn.h"
#include "RammsSportsCar.generated.h"

/**
 *  Sports car wheeled vehicle implementation
 */
UCLASS(abstract)
class ARammsSportsCar : public ARammsPawn
{
	GENERATED_BODY()

public:
	ARammsSportsCar();
};
