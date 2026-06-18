// GameMode for VR teleoperation: spawns the TeleopVRPawn so a Quest controller
// drives the Kinova arm. Select this as the map's GameMode Override.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "TeleopGameMode.generated.h"

UCLASS()
class RAMMS_API ATeleopGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ATeleopGameMode();
};
