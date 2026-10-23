// Copyright ATDev. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "RammsRobotPawn.generated.h"

class UPrimitiveComponent;

/**
 * Base pawn for physically simulated robots (wheelchairs, mobile bases, seats).
 *
 * It makes no assumption about how the body is built and creates no components of its own:
 * - a skeletal mesh simulating its physics asset (ARammsSkeletalRobotPawn, BP_Mebot_Ramms today), or
 * - a Blueprint-built assembly: a simulating root primitive (static mesh, box, ...) with further simulating
 *   parts joined by physics constraints, on this actor or in child actors (ChildActorComponent), so parts
 *   can be shared with the MuJoCo robots.
 *
 * Driving, motors, cameras switching and input live in components (RobotBase, drive controllers,
 * ControlSurface / ControlInput, RobotCamera, ...). The pawn adds no movement component, no input
 * bindings and nothing that changes the physics behind the assets' back.
 *
 * What it provides is a view of the robot as one physical thing across its parts: the main body,
 * every simulating part (including child actors'), whole-robot teleport, total mass, and optionally the
 * RobotSelf collision convention applied to all its parts.
 */
UCLASS(Blueprintable)
class RAMMS_API ARammsRobotPawn : public APawn
{
	GENERATED_BODY()

public:
	ARammsRobotPawn(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get());

	/** Component name of the main body (the chassis the robot is driven and tracked by). None: the root
	 *  component, if it is a primitive. The body should be the root so the actor follows it. */
	UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Robot|Body")
	FName BodyComponentName = NAME_None;

	/** Include the simulating parts of child actors (ChildActorComponent, recursively) in the robot. */
	UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Robot|Body")
	bool bIncludeChildActorParts = true;

	/** At BeginPlay, put every colliding part of the robot (this actor's and its child actors') on
	 *  SelfCollisionChannel and make it ignore that channel, so the robot's parts don't collide with each
	 *  other while the world still collides with all of them. Off: the parts keep the collision set on them
	 *  (BP_Mebot_Ramms sets it per component). Useful for a robot assembled from child actors, whose parts
	 *  are separate bodies that a physics constraint only stops colliding pairwise. */
	UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Robot|Body")
	bool bApplySelfCollisionChannel = false;

	/** The object type for a robot's own parts: "RobotSelf" (ECC_GameTraceChannel2) in DefaultEngine.ini. */
	UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Robot|Body", meta = (EditCondition = "bApplySelfCollisionChannel"))
	TEnumAsByte<ECollisionChannel> SelfCollisionChannel = ECC_GameTraceChannel2;

	/** The main simulated body (see BodyComponentName). */
	UFUNCTION(BlueprintPure, Category = "Robot|Body")
	UPrimitiveComponent* GetBody() const;

	/** Every separately simulated part of the robot: this actor's simulating primitives and, with
	 *  bIncludeChildActorParts, its child actors'. Welded components are left out (they are part of their
	 *  parent's body). The body first. */
	UFUNCTION(BlueprintCallable, Category = "Robot|Body")
	TArray<UPrimitiveComponent*> GetSimulatedParts() const;

	/** Actors making up the robot: this one and, with bIncludeChildActorParts, its child actors (recursively). */
	UFUNCTION(BlueprintCallable, Category = "Robot|Body")
	TArray<AActor*> GetRobotActors() const;

	/** Total mass (kg) of the simulated parts (welded components included, through their parent's body). */
	UFUNCTION(BlueprintPure, Category = "Robot|Body")
	float GetRobotMass() const;

	/** Move the whole robot so the actor ends up at NewTransform, keeping every part's pose relative to the
	 *  actor (parts of child actors and bodies of skeletal meshes included), optionally stopping it. */
	UFUNCTION(BlueprintCallable, Category = "Robot|Body")
	void TeleportRobot(const FTransform& NewTransform, bool bStopMotion = true);

	virtual void BeginPlay() override;

	/** Apply the self-collision channel to every colliding part (see bApplySelfCollisionChannel); call again
	 *  after spawning parts later. */
	UFUNCTION(BlueprintCallable, Category = "Robot|Body")
	void ApplySelfCollisionChannel();
};
