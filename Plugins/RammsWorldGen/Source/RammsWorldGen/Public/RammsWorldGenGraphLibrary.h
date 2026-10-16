// Copyright ATDev. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "RammsWorldGenGraphLibrary.generated.h"

class UPCGSpawnActorSettings;
class UPCGStaticMeshSpawnerSettings;
class UPCGGraph;
class UPCGNode;

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

	/** Replace a graph's custom Input / Output node pins (so it can be used as a subgraph with named pins). Any data type. */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void SetGraphPins(UPCGGraph* Graph, const TArray<FName>& InputPins, const TArray<FName>& OutputPins);

	/** Re-create a node's pins from its settings (after set_subgraph, for instance). */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void RefreshNodePins(UPCGNode* Node);

	/** Node comment bubble (editor only), pinned so it shows at every zoom level. */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void SetNodeComment(UPCGNode* Node, const FString& Comment);

	/** Remove every comment box from a graph (editor only). */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void ClearGraphComments(UPCGGraph* Graph);

	/** Add a comment box around a region of the graph (editor only). */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static void AddGraphComment(UPCGGraph* Graph, const FString& Text, int32 X, int32 Y, int32 Width, int32 Height, FLinearColor Color, int32 FontSize = 18);

	/** Editor only: set the view (top-left graph position, zoom) of the open graph editor showing `Graph`.
	 *  Returns the panel size in pixels (0 if the graph is not open). */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static FIntPoint SetGraphEditorView(UPCGGraph* Graph, FVector2D TopLeft, float Zoom);

	/** Editor only: save a PNG of the open graph editor panel showing `Graph`. Returns false if it is not open. */
	UFUNCTION(BlueprintCallable, Category = "Ramms|WorldGen|Graph")
	static bool CaptureGraphEditor(UPCGGraph* Graph, const FString& PngPath);

	/** The ARammsProcPiece properties the piece spawner maps (the source of truth for RammsPCG::WritePiece). */
	UFUNCTION(BlueprintPure, Category = "Ramms|WorldGen|Graph")
	static TArray<FName> PiecePropertyNames();
};
