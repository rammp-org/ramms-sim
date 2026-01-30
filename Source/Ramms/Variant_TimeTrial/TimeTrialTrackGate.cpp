// Copyright Epic Games, Inc. All Rights Reserved.


#include "TimeTrialTrackGate.h"
#include "Components/SceneComponent.h"
#include "Components/BoxComponent.h"
#include "TimeTrialPlayerController.h"

ATimeTrialTrackGate::ATimeTrialTrackGate()
{
 	PrimaryActorTick.bCanEverTick = true;

	// create the root component
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));

	// create the collision box
	CollisionBox = CreateDefaultSubobject<UBoxComponent>(TEXT("Collision Box"));
	CollisionBox->SetupAttachment(RootComponent);

	CollisionBox->SetBoxExtent(FVector(1000.0f));
	CollisionBox->SetLineThickness(32.0f);
	CollisionBox->bHiddenInGame = false;
	CollisionBox->SetCollisionProfileName(FName("OverlapAllDynamic"));

}

void ATimeTrialTrackGate::NotifyActorBeginOverlap(AActor* OtherActor)
{
	// get the player controller of the overlapping actor
	if (ATimeTrialPlayerController* PC = Cast<ATimeTrialPlayerController>(OtherActor->GetInstigatorController()))
	{
		// is this the current target marker for the player?
		if (PC->GetTargetGate() == this)
		{
			// point the player to the next marker
			PC->SetTargetGate(NextMarker);

			// if this is the finish line, increment the lap
			if (bIsFinishLine)
			{
				PC->IncrementLapCount();
			}
		}
	}
}

ATimeTrialTrackGate* ATimeTrialTrackGate::GetNextMarker() const
{
	return NextMarker;
}
