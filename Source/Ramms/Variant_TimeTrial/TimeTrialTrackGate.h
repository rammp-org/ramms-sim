// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "TimeTrialTrackGate.generated.h"

class UBoxComponent;

/**
 *  A track gate volume for a Time Trial racing game.
 *  Players must pass through the track gates in order to complete a lap.
 */
UCLASS(abstract)
class ATimeTrialTrackGate : public AActor
{
	GENERATED_BODY()
	
	/** Collision Box */
	UPROPERTY(VisibleAnywhere, Category = "Components", meta = (AllowPrivateAccess = "true"))
	UBoxComponent* CollisionBox;

protected:

	/** If this is set to true, this track gate is considered the finish line and will increase the lap when passed */
	UPROPERTY(EditAnywhere, Category="Track Gate")
	bool bIsFinishLine = false;

	/** Pointer to the next track marker in the sequence */
	UPROPERTY(EditAnywhere, Category="Track Gate")
	ATimeTrialTrackGate* NextMarker;

public:	
	
	/** Constructor */
	ATimeTrialTrackGate();

protected:

	/** Handle collision */
	virtual void NotifyActorBeginOverlap(AActor* OtherActor) override;

public:

	/** Returns the next marker on the track */
	ATimeTrialTrackGate* GetNextMarker() const;
};
