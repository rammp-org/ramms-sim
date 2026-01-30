// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "TimeTrialStartUI.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE(FCountdownFinishedDelegate);

/**
 *  A race start countdown widget.
 *  The countdown animation is performed by widget animation.
 *  Calls a delegate when the countdown is done to start the race.
 */
UCLASS(abstract)
class UTimeTrialStartUI : public UUserWidget
{
	GENERATED_BODY()
	
public:

	/** Starts the race countdown */
	void StartCountdown();

protected:

	/** Passes control to Blueprint to animate the race countdown. FinishCountdown should be called to start the race when it's done. */
	UFUNCTION(BlueprintImplementableEvent, Category="Countdown", meta = (DisplayName = "Start Countdown"))
	void BP_StartCountdown();

	/** Finishes the countdown and starts the race. */
	UFUNCTION(BlueprintCallable, Category="Countdown")
	void FinishCountdown();

public:

	FCountdownFinishedDelegate OnCountdownFinished;

};
