// Copyright ATDev. All Rights Reserved.

#include "RammsRobotPawn.h"

#include "Components/ChildActorComponent.h"
#include "Components/PrimitiveComponent.h"
#include "Components/SkeletalMeshComponent.h"

ARammsRobotPawn::ARammsRobotPawn(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
}

UPrimitiveComponent* ARammsRobotPawn::GetBody() const
{
	if (!BodyComponentName.IsNone())
	{
		TInlineComponentArray<UPrimitiveComponent*> Prims(this);
		for (UPrimitiveComponent* P : Prims)
		{
			if (P && P->GetFName() == BodyComponentName)
			{
				return P;
			}
		}
	}
	return Cast<UPrimitiveComponent>(GetRootComponent());
}

TArray<AActor*> ARammsRobotPawn::GetRobotActors() const
{
	TArray<AActor*> Out;
	Out.Add(const_cast<ARammsRobotPawn*>(this));
	if (!bIncludeChildActorParts)
	{
		return Out;
	}
	for (int32 i = 0; i < Out.Num(); ++i)
	{
		TInlineComponentArray<UChildActorComponent*> ChildComps(Out[i]);
		for (UChildActorComponent* C : ChildComps)
		{
			if (C && C->GetChildActor())
			{
				Out.AddUnique(C->GetChildActor());
			}
		}
	}
	return Out;
}

TArray<UPrimitiveComponent*> ARammsRobotPawn::GetSimulatedParts() const
{
	TArray<UPrimitiveComponent*> Out;
	if (UPrimitiveComponent* Body = GetBody())
	{
		if (Body->IsSimulatingPhysics() && !Body->IsWelded())
		{
			Out.Add(Body);
		}
	}
	for (AActor* A : GetRobotActors())
	{
		TInlineComponentArray<UPrimitiveComponent*> Prims(A);
		for (UPrimitiveComponent* P : Prims)
		{
			// Welded parts are part of their parent's body: they move and weigh with it.
			if (P && P->IsSimulatingPhysics() && !P->IsWelded())
			{
				Out.AddUnique(P);
			}
		}
	}
	return Out;
}

float ARammsRobotPawn::GetRobotMass() const
{
	float Mass = 0.f;
	for (UPrimitiveComponent* P : GetSimulatedParts())
	{
		Mass += P->GetMass();
	}
	return Mass;
}

void ARammsRobotPawn::TeleportRobot(const FTransform& NewTransform, bool bStopMotion)
{
	const FTransform Old = GetActorTransform();
	const TArray<UPrimitiveComponent*> Parts = GetSimulatedParts();

	// Where each simulating part should end up: same pose relative to the actor as now.
	TArray<FTransform> Targets;
	Targets.Reserve(Parts.Num());
	for (UPrimitiveComponent* P : Parts)
	{
		Targets.Add(P->GetComponentTransform().GetRelativeTransform(Old) * NewTransform);
	}

	SetActorTransform(NewTransform, false, nullptr, ETeleportType::TeleportPhysics);

	for (int32 i = 0; i < Parts.Num(); ++i)
	{
		// Simulating parts other than the root are detached from it, so each is placed explicitly. Moving a
		// simulating skeletal mesh with TeleportPhysics carries all its bodies along (the root's already moved
		// with the actor, so for it this is a no-op).
		UPrimitiveComponent* P = Parts[i];
		P->SetWorldTransform(Targets[i], false, nullptr, ETeleportType::TeleportPhysics);
		if (bStopMotion)
		{
			if (USkeletalMeshComponent* Sk = Cast<USkeletalMeshComponent>(P))
			{
				Sk->SetAllPhysicsLinearVelocity(FVector::ZeroVector);
				Sk->SetAllPhysicsAngularVelocityInRadians(FVector::ZeroVector);
			}
			else
			{
				P->SetPhysicsLinearVelocity(FVector::ZeroVector);
				P->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
			}
		}
	}
}

void ARammsRobotPawn::BeginPlay()
{
	Super::BeginPlay();
	if (bApplySelfCollisionChannel)
	{
		ApplySelfCollisionChannel();
	}
}

void ARammsRobotPawn::ApplySelfCollisionChannel()
{
	for (AActor* A : GetRobotActors())
	{
		TInlineComponentArray<UPrimitiveComponent*> Prims(A);
		for (UPrimitiveComponent* P : Prims)
		{
			if (P && P->IsCollisionEnabled())
			{
				P->SetCollisionObjectType(SelfCollisionChannel);
				P->SetCollisionResponseToChannel(SelfCollisionChannel, ECR_Ignore);
			}
		}
	}
}
