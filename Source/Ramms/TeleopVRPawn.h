// VR teleoperation pawn for the Kinova arm.
// Drives the arm's IK end-effector target from a Meta Quest motion controller
// (clutch + relative motion), and the gripper from the trigger.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "TeleopVRPawn.generated.h"

class USceneComponent;
class UCameraComponent;
class UMotionControllerComponent;
class UKinovaGen3ControllerComponent;
class UGripperControllerComponent;

UCLASS()
class RAMMS_API ATeleopVRPawn : public APawn
{
	GENERATED_BODY()

public:
	ATeleopVRPawn();

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void SetupPlayerInputComponent(UInputComponent* PlayerInputComponent) override;

	/** Hand controller motion is scaled by this before being applied to the arm target. */
	UPROPERTY(EditAnywhere, Category = "Teleop")
	float PositionScale = 1.0f;

	/** Grip axis past this engages the clutch (only then does the arm follow the hand). */
	UPROPERTY(EditAnywhere, Category = "Teleop", meta = (ClampMin = "0.05", ClampMax = "1.0"))
	float ClutchThreshold = 0.5f;

	/** Trigger axis past this closes the gripper. */
	UPROPERTY(EditAnywhere, Category = "Teleop", meta = (ClampMin = "0.05", ClampMax = "1.0"))
	float TriggerThreshold = 0.5f;

	/** Use the right controller (false = left). */
	UPROPERTY(EditAnywhere, Category = "Teleop")
	bool bUseRightHand = true;

	/** In-VR grip-force tuning rate (log-space units per second). Push the RIGHT thumbstick
	    up to make the grip firmer, down to make it softer; the HUD shows the live forceLim. */
	UPROPERTY(EditAnywhere, Category = "Teleop")
	float GripTuneRate = 2.0f;

protected:
	UPROPERTY(VisibleAnywhere) USceneComponent* VROrigin;
	UPROPERTY(VisibleAnywhere) UCameraComponent* Camera;
	UPROPERTY(VisibleAnywhere) UMotionControllerComponent* RightController;
	UPROPERTY(VisibleAnywhere) UMotionControllerComponent* LeftController;

	UPROPERTY() UKinovaGen3ControllerComponent* Arm = nullptr;
	UPROPERTY() UGripperControllerComponent* Gripper = nullptr;

private:
	float GripValue = 0.0f;
	float TriggerValue = 0.0f;
	bool bClutched = false;
	bool bGripperClosed = false;
	FTransform EngageControllerXf;
	FTransform EngageTargetXf;

	// the existing Target actor the arm follows (we move THIS, not a new one)
	UPROPERTY() AActor* TargetMover = nullptr;
	AActor* FindTargetActor() const;

	void OnGripAxis(float Value) { GripValue = Value; }
	void OnTriggerAxis(float Value) { TriggerValue = Value; }
	UMotionControllerComponent* ActiveController() const;
};
