// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "TimeTrialGameMode.generated.h"

class ATimeTrialTrackGate;

/**
 *  A simple GameMode for a Time Trial racing game
 */
UCLASS(abstract)
class ATimeTrialGameMode : public AGameModeBase
{
	GENERATED_BODY()
	
protected:

	/** Actor tag used to find the finish line marker on the level */
	UPROPERTY(EditAnywhere, Category="Time Trial")
	FName FinishTag;

	/** Number of laps for the race */
	UPROPERTY(EditAnywhere, Category="Time Trial")
	int32 Laps = 3;

	/** Pointer to the finish line track marker */
	TObjectPtr<ATimeTrialTrackGate> FinishLineMarker;

protected:

	/** Gameplay initialization */
	virtual void BeginPlay() override;

public: 

	/** Returns the track marker for the finish line */
	ATimeTrialTrackGate* GetFinishLine() const;

	/** Returns the number of laps for the race */
	int32 GetLaps() const { return Laps; };

};
