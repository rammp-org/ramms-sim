// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "OffroadGameMode.generated.h"

/**
 *  Simple GameMode for an offroad vehicle game
 */
UCLASS(abstract)
class AOffroadGameMode : public AGameModeBase
{
	GENERATED_BODY()
	
public:

	/** Constructor */
	AOffroadGameMode();
};
