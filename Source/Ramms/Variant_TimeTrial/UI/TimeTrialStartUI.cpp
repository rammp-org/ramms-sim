// Copyright Epic Games, Inc. All Rights Reserved.


#include "TimeTrialStartUI.h"

void UTimeTrialStartUI::StartCountdown()
{
	// pass control to BP
	BP_StartCountdown();
}

void UTimeTrialStartUI::FinishCountdown()
{
	// broadcast the delegate
	OnCountdownFinished.Broadcast();
}
