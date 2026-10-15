// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "PCG/RammsPCGCommon.h"
#include "PCGRammsHazards.generated.h"

/**
 * Dresses sidewalk sides (and park paths) with street furniture, trees and
 * hazards, deciding per object whether it leaves the access route compliant,
 * and emits one Routes point per side carrying the resulting clear width.
 *
 * Pins: In = Sidewalks (from Street Network or Park Layout);
 *       Props (palette meshes, with manifest attributes), Pieces (trees, planters, heaved slabs), Routes.
 */
UCLASS(BlueprintType, ClassGroup = (Procedural))
class RAMMSWORLDGEN_API UPCGRammsHazardPlacerSettings : public URammsPCGSettingsBase
{
	GENERATED_BODY()

public:
	/** Props per 100 m: benches, bins, lights, bollards, info boards, the odd bus stop. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (PCG_Overridable)) double PropDensity = 6.0;
	/** Hazards per 100 m: A-frames, parked scooters, bins left out, cafe seating, barriers, heaved slabs. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (PCG_Overridable)) double HazardDensity = 3.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (PCG_Overridable)) double TreeSpacing = 900.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (PCG_Overridable, ClampMin = 0, ClampMax = 1)) double CanopyChance = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (PCG_Overridable)) double StreetLightSpacing = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (PCG_Overridable)) double PlantingStrip = 0.0;
	/** Probability a hazard intrudes below the minimum clear width. NonCompliance = 0 disables intrusion entirely. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (PCG_Overridable)) double HazardIntrusionChance = 0.5;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double VerticalChangeMax = 0.64;

#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("RammsHazardPlacer")); }
	virtual FText GetDefaultNodeTitle() const override { return NSLOCTEXT("RammsPCG", "HazardsTitle", "Ramms: Hazard Placer"); }
	virtual FText GetNodeTooltipText() const override { return NSLOCTEXT("RammsPCG", "HazardsTooltip", "Street furniture, trees and hazards along sidewalk sides, with per-object clear-width compliance."); }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override;
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
	virtual FPCGElementPtr CreateElement() const override;
};

class FPCGRammsHazardPlacerElement : public FRammsPCGElementBase
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;
};

/**
 * Turns park blocks into a loop path plus a cross path, lawn trees and shrubs,
 * benches beside the paths, and the odd uneven (cobbled) segment.
 * Pins: In = Parks; Primitives, Pieces, Props, Sidewalks (path segments for the Hazard Placer), Features.
 */
UCLASS(BlueprintType, ClassGroup = (Procedural))
class RAMMSWORLDGEN_API UPCGRammsParkLayoutSettings : public URammsPCGSettingsBase
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Park", meta = (PCG_Overridable)) double PathWidth = 180.0;
	/** Trees per 100 m^2 of lawn. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Park", meta = (PCG_Overridable)) double FoliageDensity = 0.6;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Park", meta = (PCG_Overridable)) double GrassDensity = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Park", meta = (PCG_Overridable)) double BenchSpacing = 1500.0;

#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("RammsParkLayout")); }
	virtual FText GetDefaultNodeTitle() const override { return NSLOCTEXT("RammsPCG", "ParkTitle", "Ramms: Park Layout"); }
	virtual FText GetNodeTooltipText() const override { return NSLOCTEXT("RammsPCG", "ParkTooltip", "Paths, lawn trees, shrubs and benches for park blocks."); }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override;
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
	virtual FPCGElementPtr CreateElement() const override;
};

class FPCGRammsParkLayoutElement : public FRammsPCGElementBase
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;
};
