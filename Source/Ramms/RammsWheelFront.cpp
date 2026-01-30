// Copyright Epic Games, Inc. All Rights Reserved.

#include "RammsWheelFront.h"
#include "UObject/ConstructorHelpers.h"

URammsWheelFront::URammsWheelFront()
{
	AxleType = EAxleType::Front;
	bAffectedBySteering = true;
	MaxSteerAngle = 40.f;
}