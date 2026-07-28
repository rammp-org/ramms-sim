// Editor utility: generate Box-primitive physics assets for the dojo furniture
// skeletal meshes (one body per skinned bone). UE's stock generator only fits
// capsules, which collapse on flat panels like cabinet doors.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "CabinetPhysicsTools.generated.h"

class USkeletalMesh;
class UPhysicsAsset;

UCLASS()
class RAMMS_API UCabinetPhysicsTools : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Create a physics asset with one Box body per bone that has skinned
	 *  vertices, save it under PackagePath/AssetName, and assign it to Mesh.
	 *  MinSize clamps box extents (cm). bCreateConstraints adds a locked
	 *  default constraint from every child body to its parent body -- open
	 *  the hinge/prismatic axes afterwards per rig_manifest.json.
	 *  Editor builds only; returns null in game builds. */
	UFUNCTION(BlueprintCallable, Category = "Ramms|Furniture")
	static UPhysicsAsset* CreateBoxPhysicsAsset(USkeletalMesh* Mesh,
		const FString&										   PackagePath,
		const FString&										   AssetName,
		float												   MinSize = 1.0f,
		bool												   bBodyForAll = true,
		bool												   bCreateConstraints = true);
};
