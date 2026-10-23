// Copyright ATDev. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "RammsPlayerController.generated.h"

class UInputMappingContext;

/**
 * Player controller for the RAMMS game modes.
 *
 * Deliberately thin: a robot's keys come from its own components (ControlInput adds the robot's input
 * mapping context on possession, ControlSurface arbitrates), and cameras from RobotCamera. This only adds
 * project-wide input mapping contexts, if any, and keeps the controller on the possessed pawn.
 */
UCLASS(Config = "Game")
class RAMMS_API ARammsPlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	ARammsPlayerController();

protected:
	/** Input mapping contexts added for every local player, independent of the possessed pawn. */
	UPROPERTY(EditAnywhere, Category = "Input")
	TArray<TObjectPtr<UInputMappingContext>> DefaultMappingContexts;

	/** Priority the DefaultMappingContexts are added with. */
	UPROPERTY(EditAnywhere, Category = "Input")
	int32 DefaultMappingPriority = 0;

	virtual void SetupInputComponent() override;
};
