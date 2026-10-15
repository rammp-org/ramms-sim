// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "PCG/RammsPCGCommon.h"
#include "PCGRammsStreetNetwork.generated.h"

/**
 * Lays out a jittered street grid over the input bounds and emits everything
 * the street level needs: road and sidewalk slabs, curbs, curb ramps and
 * crosswalks at every crossing (some deliberately non-compliant), one point
 * per block for lot subdivision, one point per sidewalk side for hazard
 * placement, and the road centrelines as splines.
 *
 * Pins:
 *   In         the generator's bounds (the graph Input node's In pin)
 *   Primitives scaled-cube instances with Mesh + Material attributes
 *   Props      palette mesh instances (curbs) with a Mesh attribute
 *   Pieces     ARammsProcPiece points (curb ramps, fallback curbs)
 *   Blocks     one point per block, bounds = lot area, IsPark attribute
 *   Sidewalks  one point per sidewalk side with Length/Width/FurnitureZone/RouteWidth/Keepouts
 *   Roads      centreline splines
 */
UCLASS(BlueprintType, ClassGroup = (Procedural))
class RAMMSWORLDGEN_API UPCGRammsStreetNetworkSettings : public URammsPCGSettingsBase
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Site", meta = (PCG_Overridable)) double SiteSizeX = 12000.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Site", meta = (PCG_Overridable)) double SiteSizeY = 12000.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double BlockSizeMin = 5000.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double BlockSizeMax = 9000.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double RoadWidth = 700.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double SidewalkWidth = 300.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double FurnitureZoneWidth = 100.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double DecalDensity = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double PlantingStrip = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double GrassDensity = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double CurbHeight = 15.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double StreetJitter = 0.15;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double StreetDropout = 0.1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double MidblockCrossingChance = 0.2;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double CrosswalkWidth = 300.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double ParkFraction = 0.0;
	/** Probability that the ground of a built block is lawn (yards) rather than paving. 1 for residential streets. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double LawnLots = 0.0;
	/** Share of curb-side parking spots that hold a car (0 = none). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (PCG_Overridable)) double ParkingDensity = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double CurbRampFlareSlope = 0.1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double DetectableWarningDepth = 61.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double VerticalChangeMax = 0.64;

#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("RammsStreetNetwork")); }
	virtual FText GetDefaultNodeTitle() const override { return NSLOCTEXT("RammsPCG", "StreetNetworkTitle", "Ramms: Street Network"); }
	virtual FText GetNodeTooltipText() const override { return NSLOCTEXT("RammsPCG", "StreetNetworkTooltip", "Jittered street grid with sidewalks, curbs, curb ramps and crosswalks; emits blocks and sidewalk sides for the downstream nodes."); }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override;
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
	virtual FPCGElementPtr CreateElement() const override;
};

class FPCGRammsStreetNetworkElement : public FRammsPCGElementBase
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;
};
