// Copyright Epic Games, Inc. All Rights Reserved.

#include "RammsGameMode.h"
#include "RammsPlayerController.h"

ARammsGameMode::ARammsGameMode()
{
	PlayerControllerClass = ARammsPlayerController::StaticClass();
}
