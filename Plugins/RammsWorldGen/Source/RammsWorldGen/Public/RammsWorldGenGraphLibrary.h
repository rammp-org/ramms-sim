// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "RammsWorldGenGraphLibrary.generated.h"

class UPCGSpawnActorSettings;
class UPCGStaticMeshSpawnerSettings;

/**
 * Graph-authoring helpers the Python builder calls for the two spawner
 * configurations that cannot be expressed through the Python reflection
 * (attribute selectors have no Python-visible properties).
 */
UCLASS()
class RAMMSWORLDGEN_API URammsWorldGenGraphLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Spawn Actor -> ARammsProcPiece, one actor per point, attached to the generator, every piece property
	 *  overridden from the same-named attribute, Rebuild() called after spawn. */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void ConfigurePieceSpawner(UPCGSpawnActorSettings* Settings);

	/** Static Mesh Spawner selecting the mesh from the "Mesh" attribute and, optionally, slot-0 material from "Material". */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void ConfigureMeshSpawner(UPCGStaticMeshSpawnerSettings* Settings, bool bMaterialFromAttribute);

	/** Static Mesh Spawner for ground cover (grass): mesh from the "Mesh" attribute, no collision, culled with
	 *  distance (fades out 40-70 m away), no distance-field or decal cost. */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void ConfigureFoliageSpawner(UPCGStaticMeshSpawnerSettings* Settings);

	/** Static Mesh Spawner for facade modules: mesh from "Mesh", every material slot from "Material0".."Material7". */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void ConfigureModuleSpawner(UPCGStaticMeshSpawnerSettings* Settings);

	/** The ARammsProcPiece properties the piece spawner maps (the source of truth for RammsPCG::WritePiece). */
	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen|Graph")
	static TArray<FName> PiecePropertyNames();
};
