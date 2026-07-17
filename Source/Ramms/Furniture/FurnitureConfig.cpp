// Copyright Ramms. All Rights Reserved.

#include "Furniture/FurnitureConfig.h"

float UFurnitureConfig::GetTotalDrawerHeight() const
{
	float Total = 0.0f;
	for (const FFurnitureDrawerConfig& D : Drawers)
	{
		Total += D.Height;
	}
	return Total;
}

float UFurnitureConfig::GetDoorZoneHeight() const
{
	// Usable interior height minus drawer zone
	const float InteriorHeight = CabinetHeight - 2.0f * WallThickness;
	return FMath::Max(0.0f, InteriorHeight - GetTotalDrawerHeight());
}
