// Copyright Ramms. All Rights Reserved.

#include "Furniture/FurnitureGeneratorComponent.h"
#include "Furniture/FurnitureConfig.h"
#include "Components/StaticMeshComponent.h"
#include "PhysicsEngine/PhysicsConstraintComponent.h"
#include "Engine/StaticMesh.h"
#include "UObject/ConstructorHelpers.h"

UFurnitureGeneratorComponent::UFurnitureGeneratorComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	LoadCubeMesh();
}

void UFurnitureGeneratorComponent::LoadCubeMesh()
{
	static ConstructorHelpers::FObjectFinder<UStaticMesh> CubeFinder(
		TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (CubeFinder.Succeeded())
	{
		CubeMesh = CubeFinder.Object;
	}
}

void UFurnitureGeneratorComponent::BeginPlay()
{
	Super::BeginPlay();
	if (bGenerateOnBeginPlay && Config)
	{
		GenerateFurniture();
	}
}

void UFurnitureGeneratorComponent::GenerateFurniture()
{
	ClearFurniture();

	if (!Config || !CubeMesh)
	{
		UE_LOG(LogTemp, Warning, TEXT("FurnitureGenerator: Missing Config or CubeMesh."));
		return;
	}

	SpawnBody();
	SpawnDrawers();
	SpawnDoors();
}

void UFurnitureGeneratorComponent::ClearFurniture()
{
	auto DestroyComp = [](UActorComponent* Comp) {
		if (Comp)
		{
			Comp->DestroyComponent();
		}
	};

	for (auto& D : RuntimeDrawers)
	{
		DestroyComp(D.Constraint);
		DestroyComp(D.MeshComp);
	}
	for (auto& D : RuntimeDoors)
	{
		DestroyComp(D.Constraint);
		DestroyComp(D.MeshComp);
	}
	DestroyComp(BodyMesh);

	RuntimeDrawers.Empty();
	RuntimeDoors.Empty();
	BodyMesh = nullptr;
}

// ---- Component Factories ----

UStaticMeshComponent* UFurnitureGeneratorComponent::CreateBoxComponent(
	const FName&		Name,
	USceneComponent*	Parent,
	const FVector&		RelativeLocation,
	const FVector&		Scale,
	UMaterialInterface* Material,
	float				Mass,
	bool				bSimulatePhysics)
{
	AActor* Owner = GetOwner();
	if (!Owner)
		return nullptr;

	UStaticMeshComponent* Comp = NewObject<UStaticMeshComponent>(Owner, Name);
	Comp->SetStaticMesh(CubeMesh);
	Comp->SetWorldScale3D(Scale);
	Comp->SetupAttachment(Parent);
	Comp->SetRelativeLocation(RelativeLocation);
	Comp->RegisterComponent();

	if (Material)
	{
		Comp->SetMaterial(0, Material);
	}

	if (bSimulatePhysics)
	{
		Comp->SetSimulatePhysics(true);
		Comp->SetMassOverrideInKg(NAME_None, Mass);
	}

	return Comp;
}

UPhysicsConstraintComponent* UFurnitureGeneratorComponent::CreatePrismaticConstraint(
	const FName&		  Name,
	USceneComponent*	  Parent,
	UStaticMeshComponent* BodyComp,
	UStaticMeshComponent* MovableComp,
	const FVector&		  RelativeLocation,
	float				  LinearLimit,
	float				  SpringStiffness,
	float				  SpringDamping)
{
	AActor* Owner = GetOwner();
	if (!Owner)
		return nullptr;

	UPhysicsConstraintComponent* Constraint = NewObject<UPhysicsConstraintComponent>(Owner, Name);
	Constraint->SetupAttachment(Parent);
	Constraint->SetRelativeLocation(RelativeLocation);
	Constraint->RegisterComponent();

	// Wire the two bodies
	Constraint->SetConstrainedComponents(BodyComp, NAME_None, MovableComp, NAME_None);

	// Prismatic: lock all rotation, lock X and Z linear, limit Y (the slide axis = forward/back)
	Constraint->SetAngularSwing1Limit(EAngularConstraintMotion::ACM_Locked, 0.0f);
	Constraint->SetAngularSwing2Limit(EAngularConstraintMotion::ACM_Locked, 0.0f);
	Constraint->SetAngularTwistLimit(EAngularConstraintMotion::ACM_Locked, 0.0f);

	// X (side-to-side) locked, Y (forward slide) limited, Z (up/down) locked
	Constraint->SetLinearXLimit(ELinearConstraintMotion::LCM_Locked, 0.0f);
	Constraint->SetLinearYLimit(ELinearConstraintMotion::LCM_Limited, LinearLimit);
	Constraint->SetLinearZLimit(ELinearConstraintMotion::LCM_Locked, 0.0f);

	// Optional spring to pull drawer back to closed
	if (SpringStiffness > 0.0f)
	{
		Constraint->SetLinearPositionDrive(false, true, false);
		Constraint->SetLinearPositionTarget(FVector::ZeroVector);
		Constraint->SetLinearDriveParams(SpringStiffness, SpringDamping, 0.0f);
	}

	return Constraint;
}

UPhysicsConstraintComponent* UFurnitureGeneratorComponent::CreateHingeConstraint(
	const FName&		  Name,
	USceneComponent*	  Parent,
	UStaticMeshComponent* BodyComp,
	UStaticMeshComponent* DoorComp,
	const FVector&		  RelativeLocation,
	float				  MaxAngle,
	float				  SpringStiffness,
	float				  SpringDamping,
	bool				  bHingeOnRight)
{
	AActor* Owner = GetOwner();
	if (!Owner)
		return nullptr;

	UPhysicsConstraintComponent* Constraint = NewObject<UPhysicsConstraintComponent>(Owner, Name);
	Constraint->SetupAttachment(Parent);
	Constraint->SetRelativeLocation(RelativeLocation);
	Constraint->RegisterComponent();

	Constraint->SetConstrainedComponents(BodyComp, NAME_None, DoorComp, NAME_None);

	// Lock all linear axes
	Constraint->SetLinearXLimit(ELinearConstraintMotion::LCM_Locked, 0.0f);
	Constraint->SetLinearYLimit(ELinearConstraintMotion::LCM_Locked, 0.0f);
	Constraint->SetLinearZLimit(ELinearConstraintMotion::LCM_Locked, 0.0f);

	// Hinge = twist around Z (vertical axis). Lock swing.
	Constraint->SetAngularSwing1Limit(EAngularConstraintMotion::ACM_Locked, 0.0f);
	Constraint->SetAngularSwing2Limit(EAngularConstraintMotion::ACM_Locked, 0.0f);
	Constraint->SetAngularTwistLimit(EAngularConstraintMotion::ACM_Limited, MaxAngle);

	// Optional spring to close the door
	if (SpringStiffness > 0.0f)
	{
		Constraint->SetAngularDriveMode(EAngularDriveMode::TwistAndSwing);
		Constraint->SetOrientationDriveTwistAndSwing(true, false);
		Constraint->SetAngularOrientationTarget(FRotator::ZeroRotator);
		Constraint->SetAngularDriveParams(SpringStiffness, SpringDamping, 0.0f);
	}

	return Constraint;
}

// ---- Spawning Logic ----

void UFurnitureGeneratorComponent::SpawnBody()
{
	AActor*			 Owner = GetOwner();
	USceneComponent* Root = Owner->GetRootComponent();
	if (!Root)
		return;

	const float W = Config->CabinetWidth;
	const float H = Config->CabinetHeight;
	const float D = Config->CabinetDepth;

	UMaterialInterface* ExtMat = ResolveMaterial(Config->ExteriorMaterial);

	// The engine Cube mesh is 100x100x100 centered at origin, so scale = desired / 100
	FVector BodyScale(W / 100.0f, D / 100.0f, H / 100.0f);
	FVector BodyLocation(0.0f, 0.0f, H * 0.5f); // Bottom of cabinet at Z=0

	BodyMesh = CreateBoxComponent(
		FName(TEXT("FurnitureBody")),
		Root,
		BodyLocation,
		BodyScale,
		ExtMat,
		Config->BodyMass,
		Config->bBodySimulatesPhysics);
}

void UFurnitureGeneratorComponent::SpawnDrawers()
{
	if (!BodyMesh || Config->Drawers.IsEmpty())
		return;

	AActor*			 Owner = GetOwner();
	USceneComponent* Root = Owner->GetRootComponent();

	const float W = Config->CabinetWidth;
	const float D = Config->CabinetDepth;
	const float Wall = Config->WallThickness;
	const float InteriorW = W - 2.0f * Wall;
	const float InteriorD = D - Wall; // open front

	// Drawers stack from the top of the interior downward
	float CurrentZ = Config->CabinetHeight - Wall;

	for (int32 i = 0; i < Config->Drawers.Num(); ++i)
	{
		const FFurnitureDrawerConfig& DC = Config->Drawers[i];

		// Drawer occupies its height region
		CurrentZ -= DC.Height * 0.5f;

		const float DrawerH = DC.Height - 1.0f; // 1cm gap
		FVector		DrawerScale(InteriorW / 100.0f, InteriorD / 100.0f, DrawerH / 100.0f);
		FVector		DrawerLocation(0.0f, 0.0f, CurrentZ);

		UMaterialInterface* FaceMat = ResolveMaterial(DC.DrawerFaceMaterial);
		if (!FaceMat)
			FaceMat = ResolveMaterial(Config->InteriorMaterial);

		FName				  DrawerName = *FString::Printf(TEXT("Drawer_%d"), i);
		UStaticMeshComponent* DrawerComp = CreateBoxComponent(
			DrawerName,
			Root,
			DrawerLocation,
			DrawerScale,
			FaceMat,
			DC.Mass,
			true);

		if (DrawerComp)
		{
			DrawerComp->SetLinearDamping(DC.LinearDamping);

			FName						 ConstraintName = *FString::Printf(TEXT("DrawerConstraint_%d"), i);
			UPhysicsConstraintComponent* Constraint = CreatePrismaticConstraint(
				ConstraintName,
				Root,
				BodyMesh,
				DrawerComp,
				DrawerLocation,
				DC.MaxTravel,
				DC.SpringStiffness,
				DC.SpringDamping);

			FFurnitureDrawerRuntime Runtime;
			Runtime.MeshComp = DrawerComp;
			Runtime.Constraint = Constraint;
			Runtime.ConfigIndex = i;
			RuntimeDrawers.Add(Runtime);
		}

		CurrentZ -= DC.Height * 0.5f;
	}
}

void UFurnitureGeneratorComponent::SpawnDoors()
{
	if (!BodyMesh || Config->Doors.IsEmpty())
		return;

	AActor*			 Owner = GetOwner();
	USceneComponent* Root = Owner->GetRootComponent();

	const float W = Config->CabinetWidth;
	const float D = Config->CabinetDepth;
	const float Wall = Config->WallThickness;
	const float DoorH = Config->GetDoorZoneHeight();
	const float DoorZoneBottomZ = Wall + DoorH * 0.5f;
	const float InteriorW = W - 2.0f * Wall;

	// Calculate door widths
	TArray<float> DoorWidths;
	float		  UsedWidth = 0.0f;
	int32		  AutoCount = 0;
	for (const FFurnitureDoorConfig& DC : Config->Doors)
	{
		if (DC.Width > 0.0f)
		{
			DoorWidths.Add(DC.Width);
			UsedWidth += DC.Width;
		}
		else
		{
			DoorWidths.Add(0.0f);
			AutoCount++;
		}
	}
	const float AutoWidth = AutoCount > 0 ? FMath::Max(1.0f, (InteriorW - UsedWidth) / AutoCount) : 0.0f;
	for (float& DW : DoorWidths)
	{
		if (DW <= 0.0f)
			DW = AutoWidth;
	}

	// Position doors left to right
	float		CurrentX = -InteriorW * 0.5f;
	const float DoorThickness = 2.0f; // cm

	for (int32 i = 0; i < Config->Doors.Num(); ++i)
	{
		const FFurnitureDoorConfig& DC = Config->Doors[i];
		const float					DW = DoorWidths[i];

		// Door center X
		const float DoorCenterX = CurrentX + DW * 0.5f;
		// Door sits at the front face of the cabinet
		const float DoorY = -D * 0.5f + DoorThickness * 0.5f;

		FVector DoorScale(DW / 100.0f, DoorThickness / 100.0f, DoorH / 100.0f);
		FVector DoorLocation(DoorCenterX, DoorY, DoorZoneBottomZ);

		UMaterialInterface* DoorMat = ResolveMaterial(DC.DoorFaceMaterial);
		if (!DoorMat)
			DoorMat = ResolveMaterial(Config->ExteriorMaterial);

		FName				  DoorName = *FString::Printf(TEXT("Door_%d"), i);
		UStaticMeshComponent* DoorComp = CreateBoxComponent(
			DoorName,
			Root,
			DoorLocation,
			DoorScale,
			DoorMat,
			DC.Mass,
			true);

		if (DoorComp)
		{
			DoorComp->SetAngularDamping(DC.AngularDamping);

			// Hinge position: left or right edge of the door
			const float HingeX = DC.bHingeOnRight
				? (DoorCenterX + DW * 0.5f)
				: (DoorCenterX - DW * 0.5f);

			FVector HingeLocation(HingeX, DoorY, DoorZoneBottomZ);

			FName						 ConstraintName = *FString::Printf(TEXT("DoorConstraint_%d"), i);
			UPhysicsConstraintComponent* Constraint = CreateHingeConstraint(
				ConstraintName,
				Root,
				BodyMesh,
				DoorComp,
				HingeLocation,
				DC.MaxOpenAngle,
				DC.SpringStiffness,
				DC.SpringDamping,
				DC.bHingeOnRight);

			FFurnitureDoorRuntime Runtime;
			Runtime.MeshComp = DoorComp;
			Runtime.Constraint = Constraint;
			Runtime.ConfigIndex = i;
			RuntimeDoors.Add(Runtime);
		}

		CurrentX += DW;
	}
}

UMaterialInterface* UFurnitureGeneratorComponent::ResolveMaterial(
	const TSoftObjectPtr<UMaterialInterface>& SoftPtr) const
{
	if (!SoftPtr.IsNull())
	{
		return SoftPtr.LoadSynchronous();
	}
	return nullptr;
}
