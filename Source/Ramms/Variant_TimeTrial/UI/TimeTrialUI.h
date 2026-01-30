// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "TimeTrialUI.generated.h"

class UTimeTrialStartUI;

DECLARE_DYNAMIC_MULTICAST_DELEGATE(FStartRaceDelegate);

/**
 *  Simple UI for a Time Trial racing game
 *  Keeps track of lap number and best time
 *  Spawns a sub-widget to do the initial countdown
 */
UCLASS(abstract)
class UTimeTrialUI : public UUserWidget
{
	GENERATED_BODY()
	
protected:

	/** Type of start countdown UI widget to spawn */
	UPROPERTY(EditAnywhere, Category="Start Countdown")
	TSubclassOf<UTimeTrialStartUI> StartUIClass;

	/** Time when the previous lap started, in seconds */
	float LastLapTime = 0.0f;

	/** Best lap time, in seconds */
	float BestLapTime = 0.0f;

	/** Game time when this lap started */
	float LapStartTime = 0.0f;

	/** Current lap number */
	int32 CurrentLap = 0;

public:

	/** Delegate to broadcast when the race starts */
	FStartRaceDelegate OnRaceStart;

protected:

	/** Widget initialization */
	virtual void NativeConstruct() override;

public:

	/** Increments the lap and updates the lap counter */
	void UpdateLapCount(int32 Lap, float NewLapStartTime);

	/** Allows Blueprint control to update the lap tracker widgets */
	UFUNCTION(BlueprintImplementableEvent, Category="Time Trial", meta = (DisplayName = "Update Laps"))
	void BP_UpdateLaps();

protected:

	/** Called from the countdown delegate to start the race */
	UFUNCTION()
	void StartRace();

	/** Gets the current lap number */
	UFUNCTION(BlueprintPure, Category="Time Trial")
	int32 GetCurrentLap() const { return CurrentLap; };

	/** Gets the best lap time saved */
	UFUNCTION(BlueprintPure, Category="Time Trial")
	float GetBestLapTime() const { return BestLapTime; };

	/** Gets the best lap time saved */
	UFUNCTION(BlueprintPure, Category="Time Trial")
	float GetLapStartTime() const { return LapStartTime; };
};
