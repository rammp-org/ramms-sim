// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "CabinetPhysicsTools.generated.h"

class USkeletalMesh;
class UPhysicsAsset;

/**
 *  Editor-only helpers for generating Physics Assets the way Unreal's stock
 *  Python API can't: with BOX primitives and a forced body per bone.
 *
 *  The built-in auto-generator (FBX import / SkeletalMeshEditorSubsystem.create_physics_asset)
 *  always uses CAPSULE primitives, which collapse to zero bodies on flat/thin
 *  geometry (e.g. cabinet door/drawer panels) and the Python API exposes no way
 *  to change the primitive type or min bone size. This wraps
 *  FPhysicsAssetUtils::CreateFromSkeletalMesh with a configurable FPhysAssetCreateParams
 *  so it can be driven from Python.
 */
UCLASS()
class RAMMS_API UCabinetPhysicsTools : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Create (or overwrite) a Physics Asset for a Skeletal Mesh using BOX bodies.
	 *
	 * @param Mesh				The skeletal mesh to build bodies for.
	 * @param PackagePath		Content folder for the new asset, e.g. "/Game/Kitchen/Meshes/Drawer_Cabinet".
	 * @param AssetName			Asset name, e.g. "Drawer_Cabinet_PhysicsAsset".
	 * @param MinBoneSize		Bones smaller than this are ignored unless bBodyForAll is set (default 1.0).
	 * @param bBodyForAll		Force a body for every bone (recommended for handles/small parts).
	 * @param bCreateConstraints	Also create default constraints between adjacent bodies (retune per door/drawer afterwards).
	 * @return The created Physics Asset (already assigned to Mesh), or null on failure. Editor only.
	 */
	UFUNCTION(BlueprintCallable, Category = "Ramms|Physics")
	static UPhysicsAsset* CreateBoxPhysicsAsset(USkeletalMesh* Mesh,
		const FString&										   PackagePath,
		const FString&										   AssetName,
		float												   MinBoneSize = 1.0f,
		bool												   bBodyForAll = true,
		bool												   bCreateConstraints = true);
};
