// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "RammsWorldPalette.generated.h"

class UStaticMesh;
class UMaterialInterface;

/** One piece of a composite palette entry (a whole house assembled from a pack's modular
 *  meshes, captured from its blueprint at palette-build time). Relative to the entry's pivot. */
USTRUCT(BlueprintType)
struct RAMMSWORLDGEN_API FRammsPalettePart
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TSoftObjectPtr<UStaticMesh> Mesh;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	FTransform RelativeTransform;

	/** Per-slot materials as the source blueprint had them (empty = the mesh's own). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TArray<TSoftObjectPtr<UMaterialInterface>> Materials;
};

/** One mesh a palette slot can pick. Footprint and Height are read off the
 *  mesh bounds when the palette is built so placement can keep clearances
 *  without loading the mesh at generation time. */
USTRUCT(BlueprintType)
struct RAMMSWORLDGEN_API FRammsPaletteMesh
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TSoftObjectPtr<UStaticMesh> Mesh;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette", meta = (ClampMin = 0))
	float Weight = 1.0f;

	/** Plan extent (X along the mesh's forward, Y across), cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	FVector2D Footprint = FVector2D(100.0, 100.0);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	double Height = 100.0;

	/** Applied before the point transform: lets a mesh whose pivot is not at its base/centre still sit on the ground. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	FVector LocationOffset = FVector::ZeroVector;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	FRotator RotationOffset = FRotator::ZeroRotator;

	/** Uniform scale applied on top of any per-point scale. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette", meta = (ClampMin = 0.01))
	float Scale = 1.0f;

	/** Facade modules: the material category ("Bricks", "Windows", "Frame"...) of each of the mesh's
	 *  material slots, in slot order, so a node can override every slot from the building's material picks. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TArray<FName> MaterialSlots;

	/** Shelving: heights (cm above the base, at the entry's scale) of the shelf boards, measured from the mesh. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TArray<double> ShelfHeights;

	/** Composite houses: the front door's offset across the facade (facing frame, cm from the footprint
	 *  centre) and the porch floor's height above the base, so walks and manifest records meet the door. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	double EntranceOffsetY = 0.0;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	double EntranceRise = 0.0;

	/** Composite houses with a garage door on the front: the door's centre (facing frame, cm from the
	 *  footprint centre; X toward the front) and its width. GarageWidth 0 = no front garage. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	FVector2D GarageDoor = FVector2D::ZeroVector;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	double GarageWidth = 0.0;

	/** Door leaves: which end of the facing-frame Y axis carries the handle (+1 / -1; 0 = unknown). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	double HandleSide = 0.0;

	/** Composite entries (Mesh unset): every part is spawned with the entry's placement applied. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TArray<FRammsPalettePart> Parts;

	bool IsComposite() const { return Parts.Num() > 0; }
};

/** A semantic slot: what the generator asks for ("Bench", "Mat.Sidewalk",
 *  "Hazard.AFrame") rather than which asset answers. */
USTRUCT(BlueprintType)
struct RAMMSWORLDGEN_API FRammsPaletteSlot
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TArray<FRammsPaletteMesh> Meshes;

	/** For Mat.* slots, and as a material override for procedural pieces. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TSoftObjectPtr<UMaterialInterface> Material;

	/** A set to pick from (Facade.Mat.* category slots): one is chosen per building, so every module agrees. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TArray<TSoftObjectPtr<UMaterialInterface>> Materials;

	/** For slots answered by an actor class rather than a mesh (doors, buttons). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TSoftClassPtr<AActor> ActorClass;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	FText Note;
};

/** Well-known slot names. Palettes may add their own; nodes only ask for these. */
namespace RammsPaletteSlots
{
	// materials
	inline const FName MatAsphalt(TEXT("Mat.Asphalt"));
	inline const FName MatSidewalk(TEXT("Mat.Sidewalk"));
	inline const FName MatConcrete(TEXT("Mat.Concrete"));
	inline const FName MatCobble(TEXT("Mat.Cobble"));
	inline const FName MatFacade(TEXT("Mat.Facade"));
	inline const FName MatFacadeAlt(TEXT("Mat.FacadeAlt"));
	inline const FName MatGlass(TEXT("Mat.Glass"));
	inline const FName MatPaint(TEXT("Mat.Paint"));
	inline const FName MatWarning(TEXT("Mat.Warning"));
	inline const FName MatGrass(TEXT("Mat.Grass"));
	inline const FName MatLawn(TEXT("Mat.Lawn"));
	inline const FName MatPath(TEXT("Mat.Path"));
	inline const FName MatFoliage(TEXT("Mat.Foliage"));
	inline const FName MatTrunk(TEXT("Mat.Trunk"));
	inline const FName MatMetal(TEXT("Mat.Metal"));
	inline const FName MatFloorWood(TEXT("Mat.Floor.Wood"));
	inline const FName MatFloorTile(TEXT("Mat.Floor.Tile"));
	inline const FName MatFloorCarpet(TEXT("Mat.Floor.Carpet"));
	inline const FName MatWallInterior(TEXT("Mat.Wall.Interior"));
	inline const FName MatCeiling(TEXT("Mat.Ceiling"));
	inline const FName MatDoor(TEXT("Mat.Door"));
	// street meshes
	inline const FName Curb(TEXT("Curb"));
	inline const FName SidewalkCorner(TEXT("SidewalkCorner"));
	inline const FName Bench(TEXT("Bench"));
	inline const FName Bollard(TEXT("Bollard"));
	inline const FName BusStop(TEXT("BusStop"));
	inline const FName StreetLight(TEXT("StreetLight"));
	inline const FName Railing(TEXT("Railing"));
	inline const FName TrashBin(TEXT("TrashBin"));
	inline const FName InfoBoard(TEXT("InfoBoard"));
	inline const FName TreePit(TEXT("TreePit"));
	inline const FName Tree(TEXT("Tree"));
	inline const FName Shrub(TEXT("Shrub"));
	inline const FName Stairs(TEXT("Stairs"));
	// hazards (meshes that intrude into the access route)
	inline const FName HazardAFrame(TEXT("Hazard.AFrame"));
	inline const FName HazardScooter(TEXT("Hazard.Scooter"));
	inline const FName HazardBarrier(TEXT("Hazard.Barrier"));
	inline const FName HazardUpheaval(TEXT("Hazard.Upheaval"));
	inline const FName HazardCafe(TEXT("Hazard.Cafe"));
	inline const FName HazardBinOut(TEXT("Hazard.BinOut"));
	inline const FName HazardCone(TEXT("Hazard.Cone"));
	inline const FName HazardCafeChair(TEXT("Hazard.CafeChair"));
	inline const FName HazardBike(TEXT("Hazard.Bike"));
	inline const FName HazardDumpster(TEXT("Hazard.Dumpster"));
	inline const FName HazardBox(TEXT("Hazard.Box"));
	// more street furniture and dressing
	inline const FName Hydrant(TEXT("Hydrant"));
	inline const FName ParkingMeter(TEXT("ParkingMeter"));
	inline const FName NewspaperBox(TEXT("NewspaperBox"));
	inline const FName Mailbox(TEXT("Mailbox"));
	inline const FName StreetSign(TEXT("StreetSign"));
	inline const FName UtilityPole(TEXT("UtilityPole"));
	inline const FName Car(TEXT("Car"));
	inline const FName Flowerbed(TEXT("Flowerbed"));
	inline const FName Fence(TEXT("Fence"));
	inline const FName TreeSmall(TEXT("TreeSmall"));
	inline const FName Hedge(TEXT("Hedge"));
	inline const FName House(TEXT("House"));
	// facade module kits: "Facade.<style>.<Part>" mesh slots (parts below) and "Facade.Mat.<Category>" material sets
	inline const FString FacadePrefix(TEXT("Facade."));
	inline const FString FacadeMatPrefix(TEXT("Facade.Mat."));
	inline const FName FacadePartGF(TEXT("GF"));
	inline const FName FacadePartGFDoor(TEXT("GFDoor"));
	inline const FName FacadePartGFCorner(TEXT("GFCorner"));
	inline const FName FacadePartWin(TEXT("Win"));
	inline const FName FacadePartWinTop(TEXT("WinTop"));
	inline const FName FacadePartWinCorner(TEXT("WinCorner"));
	inline const FName FacadeTop(TEXT("Facade.Top"));
	inline const FName FacadeTopCorner(TEXT("Facade.TopCorner"));
	inline const FName FacadeTallTop(TEXT("Facade.TallTop"));
	inline const FName FacadeTallTopCorner(TEXT("Facade.TallTopCorner"));
	inline const FName FacadeWinCornerGeneric(TEXT("Facade.WinCorner"));
	// indoor
	inline const FName FurnitureTable(TEXT("Furniture.Table"));
	inline const FName FurnitureChair(TEXT("Furniture.Chair"));
	inline const FName FurnitureSofa(TEXT("Furniture.Sofa"));
	inline const FName FurnitureBed(TEXT("Furniture.Bed"));
	inline const FName FurnitureCupboard(TEXT("Furniture.Cupboard"));
	inline const FName FurnitureDesk(TEXT("Furniture.Desk"));
	inline const FName FurnitureBooth(TEXT("Furniture.Booth"));
	inline const FName FurniturePlant(TEXT("Furniture.Plant"));
	inline const FName FurnitureLamp(TEXT("Furniture.Lamp"));
	inline const FName FurnitureArmchair(TEXT("Furniture.Armchair"));
	inline const FName FurnitureOfficeChair(TEXT("Furniture.OfficeChair"));
	inline const FName FurnitureCoffeeTable(TEXT("Furniture.CoffeeTable"));
	inline const FName FurnitureBedTable(TEXT("Furniture.BedTable"));
	inline const FName FurnitureTV(TEXT("Furniture.TV"));
	inline const FName FurnitureTVStand(TEXT("Furniture.TVStand"));
	inline const FName FurnitureToilet(TEXT("Furniture.Toilet"));
	inline const FName FurnitureBathtub(TEXT("Furniture.Bathtub"));
	inline const FName FurniturePicture(TEXT("Furniture.Picture"));
	inline const FName FurnitureClutter(TEXT("Furniture.Clutter"));
	inline const FName FurnitureBookshelf(TEXT("Furniture.Bookshelf"));
	inline const FName FurnitureFireplace(TEXT("Furniture.Fireplace"));
	inline const FName FurnitureFloorLamp(TEXT("Furniture.FloorLamp"));
	inline const FName FurnitureAppliance(TEXT("Furniture.Appliance"));
	inline const FName FurnitureKitchenLow(TEXT("Furniture.KitchenLow"));
	inline const FName FurnitureKitchenSink(TEXT("Furniture.KitchenSink"));
	inline const FName FurnitureKitchenStove(TEXT("Furniture.KitchenStove"));
	inline const FName FurnitureKitchenDishwasher(TEXT("Furniture.KitchenDishwasher"));
	inline const FName FurnitureKitchenUpper(TEXT("Furniture.KitchenUpper"));
	inline const FName FurnitureKitchenTall(TEXT("Furniture.KitchenTall"));
	inline const FName FurnitureOfficeStorage(TEXT("Furniture.OfficeStorage"));
	inline const FName FurnitureOfficeProp(TEXT("Furniture.OfficeProp"));
	inline const FName FurnitureWhiteboard(TEXT("Furniture.Whiteboard"));
	inline const FName StoreShelf(TEXT("Store.Shelf"));
	inline const FName StoreFridge(TEXT("Store.Fridge"));
	inline const FName StoreChestFreezer(TEXT("Store.ChestFreezer"));
	inline const FName StoreCounter(TEXT("Store.Counter"));
	inline const FName StoreRegister(TEXT("Store.Register"));
	inline const FName StoreCart(TEXT("Store.Cart"));
	inline const FName StoreDisplay(TEXT("Store.Display"));
	inline const FName StoreProduct(TEXT("Store.Product"));
	inline const FName StoreProduceTable(TEXT("Store.ProduceTable"));
	inline const FName StoreCrate(TEXT("Store.Crate"));
	inline const FName StoreProduce(TEXT("Store.Produce"));
	inline const FName StoreDeliCase(TEXT("Store.DeliCase"));
	inline const FName StoreDeliItem(TEXT("Store.DeliItem"));
	inline const FName StoreSign(TEXT("Store.Sign"));
	inline const FName StoreExitSign(TEXT("Store.ExitSign"));
	inline const FName StoreBasket(TEXT("Store.Basket"));
	inline const FName StoreClutter(TEXT("Store.Clutter"));
	// building dressing
	inline const FName RoofUnit(TEXT("RoofUnit"));
	inline const FName MatMarking(TEXT("Mat.Marking"));
	inline const FName MatMarkingYellow(TEXT("Mat.MarkingYellow"));
	inline const FName MatStorefront(TEXT("Mat.Storefront"));
	inline const FName MatTrim(TEXT("Mat.Trim"));
	inline const FName MatRoof(TEXT("Mat.Roof"));
	inline const FName DoorActor(TEXT("DoorActor"));
	// interior finishes: material sets (FRammsPaletteSlot::Materials), one pick per room
	inline const FName MatWallPaint(TEXT("Mat.Wall.Paint"));
	inline const FName MatWallPaper(TEXT("Mat.Wall.Paper"));
	inline const FName MatWallTile(TEXT("Mat.Wall.Tile"));
	inline const FName MatFloorVinyl(TEXT("Mat.Floor.Vinyl"));
	inline const FName MatCurb(TEXT("Mat.Curb"));
	// door leaves (meshes, handles included; HandleSide says which edge carries the handle)
	inline const FName DoorInterior(TEXT("Door.Interior"));
	inline const FName DoorExterior(TEXT("Door.Exterior"));
	// ground cover and front-yard planting
	inline const FName GrassClump(TEXT("GrassClump"));
	inline const FName Flowers(TEXT("Flowers"));
	inline const FName FoundationShrub(TEXT("FoundationShrub"));
	inline const FName TreeLarge(TEXT("TreeLarge"));
	// projected decals (pieces of kind Decal)
	inline const FName DecalRoadCrack(TEXT("Decal.Road.Crack"));
	inline const FName DecalPothole(TEXT("Decal.Road.Pothole"));
	inline const FName DecalPatch(TEXT("Decal.Road.Patch"));
	inline const FName DecalWalkCrack(TEXT("Decal.Sidewalk.Crack"));
	inline const FName DecalStain(TEXT("Decal.Stain"));
	inline const FName DecalPuddle(TEXT("Decal.Puddle"));
}

/**
 * Maps the generator's semantic slots to concrete assets. Swap the palette to
 * re-skin a world with a different Fab pack without touching a graph.
 */
UCLASS(BlueprintType)
class RAMMSWORLDGEN_API URammsWorldPalette : public UDataAsset
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TMap<FName, FRammsPaletteSlot> Slots;

	/** Fallback material for any Mat.* slot the palette does not fill. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Palette")
	TSoftObjectPtr<UMaterialInterface> DefaultMaterial;

	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen")
	bool HasSlot(FName Slot) const;

	/** Weighted pick. Returns false when the slot is empty or missing. */
	bool PickMesh(FName Slot, const FRandomStream& Rng, FRammsPaletteMesh& OutMesh) const;

	/** Soft object path string of the slot's material, or DefaultMaterial, or empty. */
	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen")
	FString MaterialPath(FName Slot) const;

	/** Every mesh of a slot (null when the slot is missing). */
	const TArray<FRammsPaletteMesh>* GetMeshes(FName Slot) const;

	/** Random pick from the slot's material set (falls back to its single Material); empty when there is none. */
	FString PickMaterialPath(FName Slot, const FRandomStream& Rng) const;

	/** Styles that have a "Facade.<style>.GF" slot, e.g. {"dt01","dt02"}. */
	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen")
	TArray<FString> FacadeStyles() const;

	/** Slot name of a facade part: "Facade.<style>.<Part>". */
	static FName FacadeSlot(const FString& Style, FName Part);

	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen")
	FString ActorClassPath(FName Slot) const;

	/** Replace or create a slot. Used by the Python palette builder. */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen")
	void SetSlot(FName Slot, const FRammsPaletteSlot& Value);

	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen")
	void AddMesh(FName Slot, const FRammsPaletteMesh& Mesh);

	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen")
	void SetMaterial(FName Slot, TSoftObjectPtr<UMaterialInterface> Material);

	/** Append to the slot's material set. */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen")
	void AddMaterial(FName Slot, TSoftObjectPtr<UMaterialInterface> Material);

	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen")
	void SetActorClass(FName Slot, TSoftClassPtr<AActor> ActorClass);

	/** Slot names that nodes may ask for but this palette leaves empty. */
	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen")
	TArray<FName> MissingWellKnownSlots() const;
};
