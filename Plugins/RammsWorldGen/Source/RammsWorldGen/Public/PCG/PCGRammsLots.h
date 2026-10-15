// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "PCG/RammsPCGCommon.h"
#include "PCGRammsLots.generated.h"

/**
 * Splits each block (from Street Network) into street-facing lots.
 * Pins: In = Blocks; Lots = one point per lot (local +X faces the street);
 * Parks = park blocks passed through untouched.
 */
UCLASS(BlueprintType, ClassGroup = (Procedural))
class RAMMSWORLDGEN_API UPCGRammsSubdivideLotsSettings : public URammsPCGSettingsBase
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lots", meta = (PCG_Overridable)) double LotWidthMin = 1200.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lots", meta = (PCG_Overridable)) double LotWidthMax = 2500.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lots", meta = (PCG_Overridable)) double SetbackMin = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lots", meta = (PCG_Overridable)) double SetbackMax = 0.0;
	/** A block deeper than twice this gets two rows of lots (front and back frontages). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lots", meta = (PCG_Overridable)) double MinLotDepth = 1500.0;

#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("RammsSubdivideLots")); }
	virtual FText GetDefaultNodeTitle() const override { return NSLOCTEXT("RammsPCG", "LotsTitle", "Ramms: Subdivide Lots"); }
	virtual FText GetNodeTooltipText() const override { return NSLOCTEXT("RammsPCG", "LotsTooltip", "Splits blocks into street-facing lots; passes park blocks through."); }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override;
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
	virtual FPCGElementPtr CreateElement() const override;
};

class FPCGRammsSubdivideLotsElement : public FRammsPCGElementBase
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;
};

/**
 * Massing per lot: a shell with windows, and an entrance that is level,
 * stepped, stepped with a ramp, or deliberately inaccessible.
 * Pins: In = Lots; Primitives, Pieces, Props, Modules (facade kit meshes with per-slot materials), Features.
 */
UCLASS(BlueprintType, ClassGroup = (Procedural))
class RAMMSWORLDGEN_API UPCGRammsBuildingMassingSettings : public URammsPCGSettingsBase
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) int32 FloorsMin = 2;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) int32 FloorsMax = 8;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double FloorHeight = 380.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double LotCoverage = 0.9;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double EntranceStepChance = 0.35;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double EntranceRampChance = 0.6;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double WindowSpacing = 300.0;
	/** Probability that a lot with open ground beside or behind the building gets a yard tree; 0 for dense downtown lots. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double YardTreeChance = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double GrassDensity = 0.0;
	/** The street's sidewalk and furniture zone widths (from the generator params), so driveways can run out to the curb. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double SidewalkWidth = 0.0;
	/** Planting-strip streets: the lots dress the strip in front of them (street trees, grass, a street light
	 *  between driveways) because only they know where their driveways and walks cross it. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double FurnitureZoneWidth = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double PlantingStrip = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double TreeSpacing = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double CanopyChance = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double StreetLightSpacing = 0.0;
	/** House lots: probability of a driveway beside the house (sometimes with a car on it). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double DrivewayChance = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double DrivewayWidth = 360.0;
	/** House lots: probability of a hedge or picket fence along the front, with gaps for the walk and driveway. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double FrontBoundaryChance = 0.6;
	/** Non-house lots with open ground behind the building: probability of a striped rear car park with parked cars. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) double RearParkingChance = 0.0;
	/** Dress non-house buildings with the palette's modular facade kits (Facade.<style>.* slots) instead of the cube shell dressing. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) bool bFacadeModules = true;
	/** Comma-separated facade styles to draw from (palette styles not listed are ignored); empty = every style the palette has. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (PCG_Overridable)) FString FacadeStyles = TEXT("dt01,dt02,dt03");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double DoorClearWidth = 81.3;
	/** Scales the gentle mounds laid in yards (0 = flat lawns). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Terrain", meta = (PCG_Overridable)) double TerrainVariation = 1.0;
	/** Narrowest door the generator makes, even a deliberately non-compliant one: the MeBot is ~72 cm wide, so 80 cm still lets it through. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double MinPassableDoorWidth = 80.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double DoorThresholdMax = 1.27;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility", meta = (PCG_Overridable)) double VerticalChangeMax = 0.64;

#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("RammsBuildingMassing")); }
	virtual FText GetDefaultNodeTitle() const override { return NSLOCTEXT("RammsPCG", "MassingTitle", "Ramms: Building Massing"); }
	virtual FText GetNodeTooltipText() const override { return NSLOCTEXT("RammsPCG", "MassingTooltip", "Building shells with windows and level / stepped / ramped entrances per lot."); }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override;
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
	virtual FPCGElementPtr CreateElement() const override;
};

class FPCGRammsBuildingMassingElement : public FRammsPCGElementBase
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;
};
