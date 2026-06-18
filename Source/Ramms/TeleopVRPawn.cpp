#include "TeleopVRPawn.h"

#include "Camera/CameraComponent.h"
#include "Components/SceneComponent.h"
#include "MotionControllerComponent.h"
#include "HeadMountedDisplayFunctionLibrary.h"
#include "Kismet/GameplayStatics.h"
#include "InputCoreTypes.h"

#include "KinovaGen3ControllerComponent.h"
#include "GripperControllerComponent.h"

ATeleopVRPawn::ATeleopVRPawn()
{
	PrimaryActorTick.bCanEverTick = true;
	// possess as player 0 so simply placing it in the level drives the arm on Play
	AutoPossessPlayer = EAutoReceiveInput::Player0;

	VROrigin = CreateDefaultSubobject<USceneComponent>(TEXT("VROrigin"));
	RootComponent = VROrigin;

	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(VROrigin);   // bLockToHmd is true by default -> follows the headset

	RightController = CreateDefaultSubobject<UMotionControllerComponent>(TEXT("RightController"));
	RightController->SetupAttachment(VROrigin);
	RightController->SetTrackingMotionSource(FName("Right"));

	LeftController = CreateDefaultSubobject<UMotionControllerComponent>(TEXT("LeftController"));
	LeftController->SetupAttachment(VROrigin);
	LeftController->SetTrackingMotionSource(FName("Left"));
}

void ATeleopVRPawn::BeginPlay()
{
	Super::BeginPlay();

	// floor-relative tracking so the room sits at the pawn's feet (standing experience)
	UHeadMountedDisplayFunctionLibrary::SetTrackingOrigin(EHMDTrackingOrigin::LocalFloor);

	// find the Kinova arm + gripper in the level
	TArray<AActor*> Actors;
	UGameplayStatics::GetAllActorsOfClass(GetWorld(), AActor::StaticClass(), Actors);
	for (AActor* A : Actors)
	{
		if (!A) continue;
		if (UKinovaGen3ControllerComponent* K = A->FindComponentByClass<UKinovaGen3ControllerComponent>())
		{
			Arm = K;
			Gripper = A->FindComponentByClass<UGripperControllerComponent>();
			break;
		}
	}

	if (Arm)
	{
		// IMPORTANT: do NOT change the arm's control mode here. Let the arm's own
		// Blueprint/JointControl take it to its home pose on start. We switch to
		// EndEffector (IK) control only on the first grip (see Tick).
		UE_LOG(LogTemp, Log, TEXT("[Teleop] bound to arm '%s' (gripper: %s) — grip to take over"),
			*Arm->GetOwner()->GetName(), Gripper ? TEXT("found") : TEXT("none"));
	}
	else
	{
		UE_LOG(LogTemp, Warning, TEXT("[Teleop] no KinovaGen3 arm found in the level"));
	}
}

UMotionControllerComponent* ATeleopVRPawn::ActiveController() const
{
	return bUseRightHand ? RightController : LeftController;
}

AActor* ATeleopVRPawn::FindTargetActor() const
{
	// the arm's configured Target actor is the one it's following (the on-screen marker)
	if (Arm && Arm->TargetActor)
	{
		return Arm->TargetActor;
	}
	// fallback: an actor tagged "Target"
	TArray<AActor*> Found;
	UGameplayStatics::GetAllActorsWithTag(GetWorld(), FName("Target"), Found);
	return Found.Num() > 0 ? Found[0] : nullptr;
}

void ATeleopVRPawn::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	// Poll the controller axes directly. This reads the raw key state and is robust
	// against Enhanced Input / OpenXR not delivering events to legacy axis bindings.
	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		GripValue = FMath::Max(PC->GetInputAnalogKeyState(EKeys::OculusTouch_Right_Grip_Axis),
		                       PC->GetInputAnalogKeyState(EKeys::OculusTouch_Left_Grip_Axis));
		TriggerValue = FMath::Max(PC->GetInputAnalogKeyState(EKeys::OculusTouch_Right_Trigger_Axis),
		                          PC->GetInputAnalogKeyState(EKeys::OculusTouch_Left_Trigger_Axis));
	}

	// live on-screen readout (visible in the headset) for diagnosing input
	if (GEngine)
	{
		GEngine->AddOnScreenDebugMessage(1, 0.0f, FColor::Green,
			FString::Printf(TEXT("[Teleop] arm=%s  target=%s  grip=%.2f  trig=%.2f  clutch=%d  forceLim=%.0f"),
				Arm ? TEXT("ok") : TEXT("NULL"),
				TargetMover ? *TargetMover->GetName() : TEXT("none"),
				GripValue, TriggerValue, bClutched ? 1 : 0,
				Gripper ? Gripper->GetMotorForceLimit() : 0.0f));
	}

	if (!Arm) return;

	const FTransform CtrlXf = ActiveController()->GetComponentTransform();

	// ---- clutch: move the arm's Target actor while grip is held ----
	const bool bWantClutch = GripValue >= ClutchThreshold;
	if (bWantClutch && !bClutched)
	{
		bClutched = true;
		// resolve the marker we move (the on-screen target)
		if (!TargetMover)
		{
			TargetMover = FindTargetActor();
		}
		// wire the arm to FOLLOW this exact marker in IK mode (line ~384 of the
		// controller copies TargetActor's transform into the IK goal each tick)
		if (TargetMover)
		{
			Arm->ArmControlMode = EArmControlMode::EndEffectorControl;
			Arm->TargetActor = TargetMover;
		}
		EngageControllerXf = CtrlXf;                         // where the hand is now
		if (TargetMover)
		{
			EngageTargetXf = TargetMover->GetActorTransform(); // where the target is now
		}
	}
	else if (!bWantClutch && bClutched)
	{
		bClutched = false;
	}

	if (bClutched && TargetMover)
	{
		// relative motion: move the Target actor by the (scaled) hand delta since engaging.
		// controller transform is already world-space cm/left-handed -> no conversion.
		const FVector DeltaLoc = (CtrlXf.GetLocation() - EngageControllerXf.GetLocation()) * PositionScale;
		const FQuat DeltaRot = CtrlXf.GetRotation() * EngageControllerXf.GetRotation().Inverse();

		const FVector NewLoc = EngageTargetXf.GetLocation() + DeltaLoc;
		const FQuat NewRot = (DeltaRot * EngageTargetXf.GetRotation()).GetNormalized();
		TargetMover->SetActorLocationAndRotation(NewLoc, NewRot);
	}

	// ---- gripper from trigger (edge-triggered open/close) ----
	if (Gripper)
	{
		const bool bWantClose = TriggerValue >= TriggerThreshold;
		if (bWantClose && !bGripperClosed) { Gripper->Close(); bGripperClosed = true; }
		else if (!bWantClose && bGripperClosed) { Gripper->Open(); bGripperClosed = false; }
	}

	// ---- in-VR grip-force tuning: RIGHT thumbstick Y ramps the grip force cap (log-space) ----
	// Analog axis = the same reliable input path as grip/trigger. Multiplicative so it spans
	// the wide force range. Push up = firmer grip, down = softer; the HUD shows the live value.
	if (Gripper)
	{
		float StickY = 0.0f;
		if (APlayerController* PC = Cast<APlayerController>(GetController()))
		{
			StickY = PC->GetInputAnalogKeyState(EKeys::OculusTouch_Right_Thumbstick_Y);
		}
		if (FMath::Abs(StickY) > 0.5f)
		{
			const float NewLimit = Gripper->GetMotorForceLimit() * FMath::Exp(StickY * GripTuneRate * DeltaSeconds);
			Gripper->SetMotorForceLimit(FMath::Clamp(NewLimit, 100.0f, 2000000.0f));
		}
	}
}

void ATeleopVRPawn::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);

	// Raw-key axis bindings (no Input Action assets required). Right-hand Touch keys;
	// OpenXR maps the Quest Touch controllers onto these.
	PlayerInputComponent->BindAxisKey(EKeys::OculusTouch_Right_Grip_Axis, this, &ATeleopVRPawn::OnGripAxis);
	PlayerInputComponent->BindAxisKey(EKeys::OculusTouch_Right_Trigger_Axis, this, &ATeleopVRPawn::OnTriggerAxis);
	PlayerInputComponent->BindAxisKey(EKeys::OculusTouch_Left_Grip_Axis, this, &ATeleopVRPawn::OnGripAxis);
	PlayerInputComponent->BindAxisKey(EKeys::OculusTouch_Left_Trigger_Axis, this, &ATeleopVRPawn::OnTriggerAxis);
}
