// Copyright Epic Games, Inc. All Rights Reserved.

#include "RammsPlayerController.h"
#include "RammsPawn.h"
#include "RammsUI.h"
#include "EnhancedInputSubsystems.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Blueprint/UserWidget.h"
#include "Ramms.h"
#include "Kismet/GameplayStatics.h"
#include "GameFramework/PlayerStart.h"
#include "Widgets/Input/SVirtualJoystick.h"

void ARammsPlayerController::BeginPlay()
{
	Super::BeginPlay();

	// ensure we're attached to the vehicle pawn so that World Partition streaming works correctly
	bAttachToPawn = true;

	// The UI (control-surface panel + drive joystick) is spawned for every
	// local player by ramms-ui's URammsControlHUDSubsystem once a robot
	// registers a control surface; the vehicle template's HUD and touch
	// controls (VehicleUIClass / MobileControlsWidgetClass, legacy) are no
	// longer created here.
}

void ARammsPlayerController::SetupInputComponent()
{
	Super::SetupInputComponent();

	// only add IMCs for local player controllers
	if (IsLocalPlayerController())
	{
		// Add Input Mapping Contexts
		if (UEnhancedInputLocalPlayerSubsystem* Subsystem = ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(GetLocalPlayer()))
		{
			for (UInputMappingContext* CurrentContext : DefaultMappingContexts)
			{
				Subsystem->AddMappingContext(CurrentContext, 0);
			}

			// only add these IMCs if we're not using mobile touch input
			if (!ShouldUseTouchControls())
			{
				for (UInputMappingContext* CurrentContext : MobileExcludedMappingContexts)
				{
					Subsystem->AddMappingContext(CurrentContext, 0);
				}
			}
		}
	}
}

void ARammsPlayerController::Tick(float Delta)
{
	Super::Tick(Delta);

	if (IsValid(VehiclePawn) && IsValid(VehicleUI))
	{
		VehicleUI->UpdateSpeed(VehiclePawn->GetChaosVehicleMovement()->GetForwardSpeed());
		VehicleUI->UpdateGear(VehiclePawn->GetChaosVehicleMovement()->GetCurrentGear());
	}
}

void ARammsPlayerController::OnPossess(APawn* InPawn)
{
	Super::OnPossess(InPawn);

	// get a pointer to the controlled pawn. Not every possessable pawn is the
	// vehicle (e.g. a MuJoCo robot base pawn with AutoPossessPlayer); the
	// vehicle-specific respawn hook only applies when it is.
	// Drop the hook on the previous vehicle first: if it were destroyed later,
	// OnPawnDestroyed would spawn a replacement and take control away from
	// whatever pawn is possessed by then.
	if (VehiclePawn && VehiclePawn != InPawn)
	{
		VehiclePawn->OnDestroyed.RemoveDynamic(this, &ARammsPlayerController::OnPawnDestroyed);
	}
	VehiclePawn = Cast<ARammsPawn>(InPawn);
	if (VehiclePawn)
	{
		// subscribe to the pawn's OnDestroyed delegate (AddUniqueDynamic: a
		// re-possess of the same vehicle must not double-bind)
		VehiclePawn->OnDestroyed.AddUniqueDynamic(this, &ARammsPlayerController::OnPawnDestroyed);
	}
}

void ARammsPlayerController::OnPawnDestroyed(AActor* DestroyedPawn)
{
	// find the player start
	TArray<AActor*> ActorList;
	UGameplayStatics::GetAllActorsOfClass(GetWorld(), APlayerStart::StaticClass(), ActorList);

	if (ActorList.Num() > 0)
	{
		// spawn a vehicle at the player start
		const FTransform SpawnTransform = ActorList[0]->GetActorTransform();

		if (ARammsPawn* RespawnedVehicle = GetWorld()->SpawnActor<ARammsPawn>(VehiclePawnClass, SpawnTransform))
		{
			// possess the vehicle
			Possess(RespawnedVehicle);
		}
	}
}

bool ARammsPlayerController::ShouldUseTouchControls() const
{
	// are we on a mobile platform? Should we force touch?
	return SVirtualJoystick::ShouldDisplayTouchInterface() || bForceTouchControls;
}
