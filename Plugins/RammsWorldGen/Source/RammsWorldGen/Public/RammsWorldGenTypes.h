// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "RammsWorldGenTypes.generated.h"

class URammsWorldPalette;

// ---------------------------------------------------------------------------
// Scene kinds, procedural piece kinds, and the flattened parameter block that
// the PCG graphs read from the generator actor.
//
// Units are Unreal centimeters throughout. Accessibility numbers default to
// the 2010 ADA Standards (36 in = 91.4 cm minimum clear width, 1:12 ramps,
// 2% cross slope, 32 in = 81.3 cm door clear width, 1/4 in = 0.64 cm maximum
// vertical change, 1/2 in = 1.27 cm maximum threshold).
// ---------------------------------------------------------------------------

UENUM(BlueprintType)
enum class ERammsSceneKind : uint8
{
	Downtown UMETA(DisplayName = "Urban / Downtown"),
	Suburban UMETA(DisplayName = "Suburban / Residential"),
	Park     UMETA(DisplayName = "Park"),
	Indoor   UMETA(DisplayName = "Indoor"),
};

/** What an ARammsProcPiece builds. Kept small and dimension-driven so the
 *  same actor class serves every scene kind. */
UENUM(BlueprintType)
enum class ERammsProcPieceKind : uint8
{
	Slab      UMETA(ToolTip = "Flat box: road, sidewalk, floor, lawn. SizeX/Y plan, SizeZ thickness; top face at the actor origin."),
	Curb      UMETA(ToolTip = "Curb block along +X: SizeX length, SizeY depth, SizeZ = curb height."),
	CurbRamp  UMETA(ToolTip = "Curb ramp descending toward +X: Rise = curb height, Slope = running slope, SizeY = ramp width, flares on both sides."),
	Step      UMETA(ToolTip = "One or more steps rising toward -X: Rise per step, StepCount steps, SizeY width, SizeX tread depth."),
	Ramp      UMETA(ToolTip = "Straight ramp rising toward -X: Rise total, Slope running slope, SizeY width, with a level landing of LandingSize at the top."),
	Wall      UMETA(ToolTip = "Wall along +X: SizeX length, SizeY thickness, SizeZ height; OpeningWidth > 0 cuts a door opening centred at OpeningOffset."),
	Door      UMETA(ToolTip = "Door leaf: SizeX width, SizeY thickness, SizeZ height; Rise = threshold height."),
	Bollard   UMETA(ToolTip = "Cylinder: SizeX diameter, SizeZ height."),
	Tree      UMETA(ToolTip = "Low-poly tree: SizeX canopy diameter, SizeZ total height; trunk is 12% of canopy."),
	Shrub     UMETA(ToolTip = "Low-poly shrub: SizeX diameter, SizeZ height."),
	Planter   UMETA(ToolTip = "Open box planter: SizeX/SizeY plan, SizeZ height."),
	Column    UMETA(ToolTip = "Square column: SizeX side, SizeZ height."),
	Stairs    UMETA(ToolTip = "Alias of Step with StepCount >= 3; kept for manifest readability."),
	Roof      UMETA(ToolTip = "Gable roof: SizeX span across the ridge, SizeY ridge length, SizeZ rise; sits with its eaves at the origin."),
	Decal     UMETA(ToolTip = "Projected decal (crack, pothole, stain): SizeX length, SizeY width, SizeZ projection depth; MaterialPath is a deferred-decal material; centred on the origin, projecting down."),
	Mound     UMETA(ToolTip = "Grassy mound (or, with a negative Rise, a hollow): SizeX/SizeY plan diameters of an elliptical cosine bump Rise high, centred on the origin; its rim sits 2 cm under the ground."),
	Patch     UMETA(ToolTip = "Flat elliptical ground patch (pond water, mud, gravel): SizeX/SizeY diameters, top SizeZ above the origin."),
};

/** Why a generated feature is tagged non-compliant. Carried into the manifest. */
UENUM(BlueprintType)
enum class ERammsComplianceIssue : uint8
{
	None,
	ClearWidthBelowMinimum,
	SlopeTooSteep,
	CrossSlopeTooSteep,
	MissingCurbRamp,
	StepAtEntrance,
	DoorTooNarrow,
	ThresholdTooHigh,
	VerticalChangeTooHigh,
	SurfaceUneven,
	ObstacleInRoute,
};

/** One generated feature worth knowing about: a hazard, a ramp, a door, an
 *  entrance, a crossing. The manifest is the ground truth for datasets. */
USTRUCT(BlueprintType)
struct RAMMSWORLDGEN_API FRammsManifestFeature
{
	GENERATED_BODY()

	/** Short kind name: Hazard, CurbRamp, Crossing, Entrance, Door, Ramp, Step, Bollard, Prop, Tree, Room ... */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FName Kind;

	/** Finer type inside the kind, e.g. the hazard catalog entry or the room kind. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FName Subtype;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FVector Location = FVector::ZeroVector;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FRotator Rotation = FRotator::ZeroRotator;

	/** Plan size and height, in cm. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FVector Size = FVector::ZeroVector;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	bool bCompliant = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	ERammsComplianceIssue Issue = ERammsComplianceIssue::None;

	/** The measured quantity that decided compliance, in the feature's natural unit
	 *  (cm for widths/heights, rise/run for slopes). */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	double Measure = 0.0;

	/** The threshold that quantity was compared against. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	double Threshold = 0.0;
};

/** A pedestrian route the generator intends to be traversable. Clear width is
 *  the narrowest point after hazards were placed. */
USTRUCT(BlueprintType)
struct RAMMSWORLDGEN_API FRammsManifestRoute
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FName Name;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	TArray<FVector> Points;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	double NominalWidth = 0.0;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	double MinClearWidth = 0.0;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	bool bCompliant = true;
};

USTRUCT(BlueprintType)
struct RAMMSWORLDGEN_API FRammsWorldManifest
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	int32 Seed = 0;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FName Preset;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	ERammsSceneKind SceneKind = ERammsSceneKind::Downtown;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FBox Bounds = FBox(ForceInit);

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	TArray<FRammsManifestFeature> Features;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	TArray<FRammsManifestRoute> Routes;

	/** Suggested spawn pose for the wheelchair: on a sidewalk or indoor floor,
	 *  facing along the first route. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = "Manifest")
	FTransform SuggestedStart = FTransform::Identity;

	int32 CountIssues() const
	{
		int32 N = 0;
		for (const FRammsManifestFeature& F : Features) { N += F.bCompliant ? 0 : 1; }
		return N;
	}
};

/**
 * The flattened parameter block a generator actor exposes to its PCG graph.
 *
 * Every member name is also the name of the matching PCG_Overridable property
 * on the custom nodes, so a single "Get Actor Property (Self, Params)" node
 * wired into each node's Overrides pin drives the whole graph. Add a parameter
 * here, add a same-named property to the node that consumes it, and the wiring
 * already exists.
 */
USTRUCT(BlueprintType)
struct RAMMSWORLDGEN_API FRammsWorldGenParams
{
	GENERATED_BODY()

	// --- site --------------------------------------------------------------
	/** The palette answering every mesh/material slot. Travels with the params so one Get Actor Property node carries it. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Site") TSoftObjectPtr<URammsWorldPalette> Palette;
	/** Generation extent in X, cm. The generator's volume is sized to match. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Site") double SiteSizeX = 12000.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Site") double SiteSizeY = 12000.0;
	/** Probability (0..1) that any individual feature is generated non-compliant. 0 = fully accessible world. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Site", meta = (ClampMin = 0, ClampMax = 1)) double NonCompliance = 0.15;

	// --- streets -----------------------------------------------------------
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double BlockSizeMin = 5000.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double BlockSizeMax = 9000.0;
	/** Carriageway width, curb face to curb face. 700 = two lanes. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double RoadWidth = 700.0;
	/** Total sidewalk width, curb face to building line. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double SidewalkWidth = 300.0;
	/** Strip next to the curb where props, trees and hazards live. The rest is the pedestrian access route. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double FurnitureZoneWidth = 100.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double CurbHeight = 15.0;
	/** 0 = perfect grid, 1 = heavily jittered intersections. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (ClampMin = 0, ClampMax = 1)) double StreetJitter = 0.15;
	/** Probability an interior street segment is removed, merging two blocks. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (ClampMin = 0, ClampMax = 1)) double StreetDropout = 0.1;
	/** Probability of a mid-block crossing on a block face. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (ClampMin = 0, ClampMax = 1)) double MidblockCrossingChance = 0.2;
	/** Crosswalk width along the road. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double CrosswalkWidth = 300.0;

	// --- lots and buildings --------------------------------------------------
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") double LotWidthMin = 1200.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") double LotWidthMax = 2500.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") double SetbackMin = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") double SetbackMax = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") int32 FloorsMin = 2;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") int32 FloorsMax = 8;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") double FloorHeight = 380.0;
	/** Fraction of a lot's frontage the building occupies. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (ClampMin = 0.2, ClampMax = 1)) double LotCoverage = 0.9;
	/** Probability an entrance has a step rather than being level or ramped. Scaled by NonCompliance. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (ClampMin = 0, ClampMax = 1)) double EntranceStepChance = 0.35;
	/** Probability a stepped entrance also gets a compliant ramp beside it. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (ClampMin = 0, ClampMax = 1)) double EntranceRampChance = 0.6;
	/** Window spacing along a facade; 0 disables windows. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") double WindowSpacing = 300.0;
	/** Comma-separated modular facade kits (palette Facade.<style>.* slots) buildings draw from, e.g. "dt01,dt02" (downtown) or "sb01,sb02,sb03" (small business). Empty = all. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings") FString FacadeStyles = TEXT("dt01,dt02,dt03");
	/** Probability that open ground behind a (non-house) building becomes a striped car park with parked cars. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Buildings", meta = (ClampMin = 0, ClampMax = 1)) double RearParkingChance = 0.0;

	// --- street furniture, trees, hazards -------------------------------------
	/** Props (benches, bins, lights) per 100 m of sidewalk. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards") double PropDensity = 6.0;
	/** Hazards per 100 m of sidewalk: A-frames, parked scooters, bins out, construction, upheaval. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards") double HazardDensity = 3.0;
	/** Spacing of street trees in the furniture zone; 0 = none. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards") double TreeSpacing = 900.0;
	/** Probability that a sidewalk side is a canopy street: large old trees closer together, in pits or the planting strip. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (ClampMin = 0, ClampMax = 1)) double CanopyChance = 0.0;
	/** Street lights every this many cm along each sidewalk (staggered between the two sides); 0 = only random ones. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards") double StreetLightSpacing = 0.0;
	/** Projected decals per 100 m of street: asphalt cracks, potholes, patches, manholes, sidewalk cracks and stains. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double DecalDensity = 0.0;
	/** 1 = the furniture zone is a grass planting strip (residential streets) instead of paving. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets") double PlantingStrip = 0.0;
	/** Grass clumps per m^2 on lawns, yards, planting strips and park grass; 0 = bare lawn material. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban") double GrassDensity = 0.0;
	/** Probability that a placed hazard intrudes into the access route below the minimum clear width. Scaled by NonCompliance. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Hazards", meta = (ClampMin = 0, ClampMax = 1)) double HazardIntrusionChance = 0.5;

	// --- accessibility profile -------------------------------------------------
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double MinClearWidth = 91.4;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double PreferredClearWidth = 152.4;
	/** Rise over run. 0.0833 = 1:12. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double RampMaxSlope = 0.0833;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double MaxCrossSlope = 0.02;
	/** Curb ramp flare slope, rise over run. 0.1 = 1:10. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double CurbRampFlareSlope = 0.1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double DoorClearWidth = 81.3;
	/** Scales the gentle mounds laid in yards (0 = flat lawns). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Terrain") double TerrainVariation = 1.0;
	/** Narrowest door the generator makes, even a deliberately non-compliant one: the MeBot is ~72 cm wide, so 80 cm still lets it through. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double MinPassableDoorWidth = 80.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double DoorThresholdMax = 1.27;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double VerticalChangeMax = 0.64;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double LandingSize = 152.4;
	/** Detectable-warning strip depth at the bottom of curb ramps. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Accessibility") double DetectableWarningDepth = 61.0;

	// --- suburban / park ---------------------------------------------------------
	/** Fraction of blocks converted to park (no lots; paths, lawn, trees). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban", meta = (ClampMin = 0, ClampMax = 1)) double ParkFraction = 0.0;
	/** Share of curb-side parking spots that hold a parked car. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streets", meta = (ClampMin = 0, ClampMax = 1)) double ParkingDensity = 0.0;
	/** Probability that a built block's ground is lawn (yards) rather than paving. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban", meta = (ClampMin = 0, ClampMax = 1)) double LawnLots = 0.0;
	/** Probability that a lot with open ground gets a yard tree. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban", meta = (ClampMin = 0, ClampMax = 1)) double YardTreeChance = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban", meta = (ClampMin = 0, ClampMax = 1)) double DrivewayChance = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban") double DrivewayWidth = 360.0;
	/** Probability a house lot has a hedge or fence along its front (gaps for the walk and driveway). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban", meta = (ClampMin = 0, ClampMax = 1)) double FrontBoundaryChance = 0.6;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban") double PathWidth = 180.0;
	/** Trees per 100 m^2 of park. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Suburban") double FoliageDensity = 0.6;

	// --- indoor -----------------------------------------------------------------
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor") double RoomSizeMin = 350.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor") double RoomSizeMax = 800.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor") double CorridorWidth = 180.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor") double WallThickness = 15.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor") double WallHeight = 280.0;
	/** Door leaf width distribution. The mean sits above the ADA minimum; the spread produces some narrow doors. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor") double DoorWidthMean = 86.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor") double DoorWidthStd = 8.0;
	/** Probability a door gets a raised threshold. Scaled by NonCompliance. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (ClampMin = 0, ClampMax = 1)) double ThresholdChance = 0.3;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (ClampMin = 0, ClampMax = 1)) double FurnitureDensity = 0.5;
	/** 0 = a home (living rooms, bedrooms, dining), 1 = a workplace (offices, meeting rooms, a break room). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (ClampMin = 0, ClampMax = 1)) double OfficeFraction = 0.0;
	/** Probability a room is retail (shop floor with aisles; small rooms become stock rooms). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (ClampMin = 0, ClampMax = 1)) double RetailFraction = 0.0;
	/** Probability an interior room is a corridor-connected room vs. open plan. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Indoor", meta = (ClampMin = 0, ClampMax = 1)) double CorridorChance = 0.6;
};
