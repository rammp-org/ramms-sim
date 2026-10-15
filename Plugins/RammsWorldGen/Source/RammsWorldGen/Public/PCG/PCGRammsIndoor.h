// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "PCG/RammsPCGCommon.h"
#include "PCGRammsIndoor.generated.h"

/**
 * Partitions the input bounds into rooms (a corridor with rooms off it, or an
 * open BSP plan), builds walls with door openings, door leaves (some narrow,
 * some with raised thresholds), floors by room kind, and furniture placed
 * against walls and around tables while keeping (or deliberately breaking)
 * the clear route between a room's doors.
 *
 * Pins: In = bounds; Pieces (walls, doors, thresholds), Primitives (floors),
 *       Props (furniture), Routes (door-to-centre segments), Features (rooms).
 */
UCLASS(BlueprintType, ClassGroup = (Procedural))
class RAMMSWORLDGEN_API UPCGRammsIndoorLayoutSettings : public URammsPCGSettingsBase
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Site", meta = (PCG_Overridable)) double SiteSizeX = 2400.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Site", meta = (PCG_Overridable)) double SiteSizeY = 1600.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double RoomSizeMin = 350.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double RoomSizeMax = 800.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double CorridorWidth = 180.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double CorridorChance = 0.6;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double WallThickness = 15.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double WallHeight = 280.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double DoorWidthMean = 86.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double DoorWidthStd = 8.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double ThresholdChance = 0.3;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double FurnitureDensity = 0.5;
	/** 0 = a home (living rooms, bedrooms, dining), 1 = a workplace (offices, meeting rooms, a break room). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double OfficeFraction = 0.0;
	/** Probability a room is retail: large rooms become shop floors (gondola aisles, wall freezers, a checkout), small ones stock rooms. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double RetailFraction = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (PCG_Overridable)) double HazardIntrusionChance = 0.5;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double DoorClearWidth = 81.3;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double DoorThresholdMax = 1.27;

#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("RammsIndoorLayout")); }
	virtual FText GetDefaultNodeTitle() const override { return NSLOCTEXT("RammsPCG", "IndoorTitle", "Ramms: Indoor Layout"); }
	virtual FText GetNodeTooltipText() const override { return NSLOCTEXT("RammsPCG", "IndoorTooltip", "Rooms, walls, doors, floors and furniture with door and route compliance."); }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override;
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
	virtual FPCGElementPtr CreateElement() const override;
};

class FPCGRammsIndoorLayoutElement : public FRammsPCGElementBase
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;
};
