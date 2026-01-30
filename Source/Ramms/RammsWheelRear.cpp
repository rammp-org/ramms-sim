// Copyright Epic Games, Inc. All Rights Reserved.

#include "RammsWheelRear.h"
#include "UObject/ConstructorHelpers.h"

URammsWheelRear::URammsWheelRear()
{
	AxleType = EAxleType::Rear;
	bAffectedByHandbrake = true;
	bAffectedByEngine = true;
}