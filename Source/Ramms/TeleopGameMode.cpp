#include "TeleopGameMode.h"
#include "TeleopVRPawn.h"

ATeleopGameMode::ATeleopGameMode()
{
	// Spawn the VR teleop pawn for the player; keep the default PlayerController.
	DefaultPawnClass = ATeleopVRPawn::StaticClass();
}
