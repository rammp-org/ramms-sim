// Copyright Epic Games, Inc. All Rights Reserved.


#include "TimeTrialGameMode.h"
#include "Kismet/GameplayStatics.h"
#include "TimeTrialTrackGate.h"
#include "Engine/World.h"

void ATimeTrialGameMode::BeginPlay()
{
	Super::BeginPlay();

	// get the finish line marker
	TArray<AActor*> ActorList;

	UGameplayStatics::GetAllActorsOfClassWithTag(GetWorld(), ATimeTrialTrackGate::StaticClass(), FinishTag, ActorList);

	if (ActorList.Num() > 0)
	{
		// get the first returned track marker that matches the tag
		FinishLineMarker = Cast<ATimeTrialTrackGate>(ActorList[0]);
	}

}

ATimeTrialTrackGate* ATimeTrialGameMode::GetFinishLine() const
{
	return FinishLineMarker;
}
