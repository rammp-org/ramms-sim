// Copyright ATDev. All Rights Reserved.

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/ChildActorComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "Misc/ScopeExit.h"
#include "RammsRobotPawn.h"

// A robot assembled from simulating static meshes, one of them in a child actor, the way a future seat /
// base built from Blueprint parts would be: the pawn has to see it as one robot (parts, mass, teleport,
// self-collision) without a skeletal mesh. Run: Session Frontend > Automation, "Ramms.RobotPawn".
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRammsRobotPawnAssemblyTest, "Ramms.RobotPawn.Assembly",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FRammsRobotPawnAssemblyTest::RunTest(const FString& Parameters)
{
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.SetCurrentWorld(World);
	ON_SCOPE_EXIT
	{
		World->DestroyWorld(false);
		GEngine->DestroyWorldContext(World);
	};

	UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (!TestNotNull(TEXT("engine cube"), Cube))
	{
		return false;
	}

	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	ARammsRobotPawn* Pawn = World->SpawnActor<ARammsRobotPawn>(FVector(0, 0, 300), FRotator::ZeroRotator, Params);
	if (!TestNotNull(TEXT("pawn"), Pawn))
	{
		return false;
	}

	// Chassis: a simulating static mesh as the root.
	UStaticMeshComponent* Chassis = NewObject<UStaticMeshComponent>(Pawn, TEXT("Chassis"));
	Chassis->SetMobility(EComponentMobility::Movable);
	Chassis->SetStaticMesh(Cube);
	Chassis->SetSimulatePhysics(true);
	Pawn->SetRootComponent(Chassis);
	Chassis->RegisterComponent();
	Pawn->SetActorLocation(FVector(0, 0, 300));

	// A cover welded to the chassis: part of the chassis body, not a separate part.
	UStaticMeshComponent* Cover = NewObject<UStaticMeshComponent>(Pawn, TEXT("Cover"));
	Cover->SetMobility(EComponentMobility::Movable);
	Cover->SetStaticMesh(Cube);
	Cover->SetupAttachment(Chassis);
	Cover->SetRelativeLocation(FVector(0, 0, 100));
	Cover->RegisterComponent();

	// Seat: a separate simulating body in a child actor, 150 cm ahead of the chassis.
	UChildActorComponent* SeatSlot = NewObject<UChildActorComponent>(Pawn, TEXT("SeatSlot"));
	SeatSlot->SetupAttachment(Chassis);
	SeatSlot->SetRelativeLocation(FVector(150, 0, 0));
	SeatSlot->SetChildActorClass(AStaticMeshActor::StaticClass());
	SeatSlot->RegisterComponent();
	AStaticMeshActor* Seat = Cast<AStaticMeshActor>(SeatSlot->GetChildActor());
	if (!TestNotNull(TEXT("child actor"), Seat))
	{
		return false;
	}
	UStaticMeshComponent* SeatMesh = Seat->GetStaticMeshComponent();
	SeatMesh->SetMobility(EComponentMobility::Movable);
	SeatMesh->SetStaticMesh(Cube);
	SeatMesh->SetSimulatePhysics(true);

	TestTrue(TEXT("body is the root primitive"), Pawn->GetBody() == Chassis);

	const TArray<AActor*> Actors = Pawn->GetRobotActors();
	TestEqual(TEXT("robot actors: pawn + child actor"), Actors.Num(), 2);
	TestTrue(TEXT("child actor is part of the robot"), Actors.Contains(Seat));

	const TArray<UPrimitiveComponent*> Parts = Pawn->GetSimulatedParts();
	TestEqual(TEXT("simulated parts: chassis + seat (cover is welded)"), Parts.Num(), 2);
	TestTrue(TEXT("chassis first"), Parts.Num() > 0 && Parts[0] == Chassis);
	TestTrue(TEXT("seat included"), Parts.Contains(SeatMesh));
	TestFalse(TEXT("welded cover excluded"), Parts.Contains(Cover));

	const float Mass = Pawn->GetRobotMass();
	TestTrue(TEXT("mass sums the parts"), FMath::IsNearlyEqual(Mass, Chassis->GetMass() + SeatMesh->GetMass(), 0.01f) && Mass > 0.f);

	// Teleport: everything keeps its pose relative to the actor.
	const FVector SeatOffsetBefore = SeatMesh->GetComponentLocation() - Chassis->GetComponentLocation();
	const FTransform Target(FRotator(0, 90, 0), FVector(500, 200, 400));
	Pawn->TeleportRobot(Target, true);
	TestTrue(TEXT("actor at target"), Pawn->GetActorLocation().Equals(Target.GetLocation(), 0.1));
	TestTrue(TEXT("chassis at target"), Chassis->GetComponentLocation().Equals(Target.GetLocation(), 0.1));
	const FVector SeatOffsetAfter = SeatMesh->GetComponentLocation() - Chassis->GetComponentLocation();
	TestTrue(FString::Printf(TEXT("seat offset rotated with the robot (%s -> %s)"), *SeatOffsetBefore.ToString(), *SeatOffsetAfter.ToString()),
		SeatOffsetAfter.Equals(Target.GetRotation().RotateVector(SeatOffsetBefore), 0.5));
	TestTrue(TEXT("welded cover followed"), Cover->GetComponentLocation().Equals(Target.TransformPosition(FVector(0, 0, 100)), 0.5));

	// Self-collision convention across actors.
	Pawn->ApplySelfCollisionChannel();
	for (UPrimitiveComponent* P : { static_cast<UPrimitiveComponent*>(Chassis), static_cast<UPrimitiveComponent*>(SeatMesh) })
	{
		TestEqual(*FString::Printf(TEXT("%s object type"), *P->GetName()), static_cast<int32>(P->GetCollisionObjectType()), static_cast<int32>(Pawn->SelfCollisionChannel.GetValue()));
		TestEqual(*FString::Printf(TEXT("%s ignores its own robot"), *P->GetName()), static_cast<int32>(P->GetCollisionResponseToChannel(Pawn->SelfCollisionChannel)), static_cast<int32>(ECR_Ignore));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
