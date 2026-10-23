// Copyright ATDev. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "RammsRobotPawn.h"
#include "RammsSkeletalRobotPawn.generated.h"

class UCameraComponent;
class USkeletalMeshComponent;
class USpringArmComponent;

/**
 * A robot whose body is one skeletal mesh simulating its physics asset in Chaos (BP_Mebot_Ramms,
 * BP_Mebot_Mujoco): the mesh is the root, plus a seat camera and a chase camera on booms.
 *
 * The component and property names are the ones these robots had under the old vehicle-template parent
 * (AWheeledVehiclePawn / ARammsPawn), so their Blueprint overrides and socket attachments carry over:
 * the root is still the "VehicleMesh" subobject (also what RobotBase's ChaosSkeletalMeshComponentName
 * points at) and the camera booms keep their names and defaults.
 */
UCLASS(Abstract, Blueprintable)
class RAMMS_API ARammsSkeletalRobotPawn : public ARammsRobotPawn
{
	GENERATED_BODY()

public:
	ARammsSkeletalRobotPawn(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get());

	/** Name of the root skeletal-mesh subobject, kept from the vehicle template for asset compatibility. */
	static const FName MeshComponentName;

	UFUNCTION(BlueprintPure, Category = "Robot")
	USkeletalMeshComponent* GetMesh() const { return Mesh; }

	UFUNCTION(BlueprintPure, Category = "Robot|Camera")
	USpringArmComponent* GetFrontSpringArm() const { return FrontSpringArm; }

	UFUNCTION(BlueprintPure, Category = "Robot|Camera")
	UCameraComponent* GetFrontCamera() const { return FrontCamera; }

	UFUNCTION(BlueprintPure, Category = "Robot|Camera")
	USpringArmComponent* GetBackSpringArm() const { return BackSpringArm; }

	UFUNCTION(BlueprintPure, Category = "Robot|Camera")
	UCameraComponent* GetBackCamera() const { return BackCamera; }

private:
	/** Root: the robot's skeletal mesh, simulating physics. */
	UPROPERTY(Category = "Robot", VisibleDefaultsOnly, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	TObjectPtr<USkeletalMeshComponent> Mesh;

	/** Boom for the seat camera (no arm length by default). */
	UPROPERTY(Category = "Robot|Camera", VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	TObjectPtr<USpringArmComponent> FrontSpringArm;

	UPROPERTY(Category = "Robot|Camera", VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	TObjectPtr<UCameraComponent> FrontCamera;

	/** Boom for the third-person chase camera. */
	UPROPERTY(Category = "Robot|Camera", VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	TObjectPtr<USpringArmComponent> BackSpringArm;

	UPROPERTY(Category = "Robot|Camera", VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	TObjectPtr<UCameraComponent> BackCamera;
};
