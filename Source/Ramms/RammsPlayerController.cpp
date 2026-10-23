// Copyright ATDev. All Rights Reserved.

#include "RammsPlayerController.h"

#include "Engine/LocalPlayer.h"
#include "EnhancedInputSubsystems.h"
#include "InputMappingContext.h"

ARammsPlayerController::ARammsPlayerController()
{
	// Follow the possessed pawn (audio listener, streaming source).
	bAttachToPawn = true;
}

void ARammsPlayerController::SetupInputComponent()
{
	Super::SetupInputComponent();

	if (!IsLocalPlayerController() || DefaultMappingContexts.IsEmpty())
	{
		return;
	}
	if (UEnhancedInputLocalPlayerSubsystem* Subsystem = ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(GetLocalPlayer()))
	{
		for (UInputMappingContext* Context : DefaultMappingContexts)
		{
			if (Context)
			{
				Subsystem->AddMappingContext(Context, DefaultMappingPriority);
			}
		}
	}
}
