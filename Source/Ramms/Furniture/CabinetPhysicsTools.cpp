// Copyright Epic Games, Inc. All Rights Reserved.

#include "CabinetPhysicsTools.h"
#include "Engine/SkeletalMesh.h"
#include "PhysicsEngine/PhysicsAsset.h"

#if WITH_EDITOR
	#include "PhysicsAssetUtils.h" // FPhysicsAssetUtils, FPhysAssetCreateParams, EFG_Box (module: PhysicsUtilities)
	#include "AssetRegistry/AssetRegistryModule.h"
	#include "UObject/Package.h"
	#include "UObject/UObjectGlobals.h" // CreatePackage
#endif

UPhysicsAsset* UCabinetPhysicsTools::CreateBoxPhysicsAsset(USkeletalMesh* Mesh,
	const FString&														  PackagePath,
	const FString&														  AssetName,
	float																  MinBoneSize,
	bool																  bBodyForAll,
	bool																  bCreateConstraints)
{
#if WITH_EDITOR
	if (!Mesh)
	{
		UE_LOG(LogTemp, Warning, TEXT("CreateBoxPhysicsAsset: Mesh is null."));
		return nullptr;
	}

	const FString PackageName = PackagePath / AssetName;
	UPackage*	  Package = CreatePackage(*PackageName);
	if (!Package)
	{
		UE_LOG(LogTemp, Warning, TEXT("CreateBoxPhysicsAsset: could not create package %s"), *PackageName);
		return nullptr;
	}
	Package->FullyLoad();

	UPhysicsAsset* PhysicsAsset = NewObject<UPhysicsAsset>(
		Package, FName(*AssetName), RF_Public | RF_Standalone | RF_Transactional);

	// Body/constraint generation parameters -- the bits the Python API hides.
	FPhysAssetCreateParams Params;
	Params.MinBoneSize = MinBoneSize;
	Params.GeomType = EFG_Box;			  // <-- box bodies fit flat panels (capsules don't)
	Params.bBodyForAll = bBodyForAll;	  // one body per bone (handles included)
	Params.bWalkPastSmall = !bBodyForAll; // when not forcing all, skip tiny bones
	Params.bAutoOrientToBone = true;
	Params.bCreateConstraints = bCreateConstraints;
	Params.bDisableCollisionsByDefault = true;

	FText	   ErrorMessage;
	const bool bOk = FPhysicsAssetUtils::CreateFromSkeletalMesh(
		PhysicsAsset, Mesh, Params, ErrorMessage,
		/*bSetToMesh=*/true, /*bShowProgress=*/false);

	if (!bOk)
	{
		UE_LOG(LogTemp, Warning, TEXT("CreateBoxPhysicsAsset failed for %s: %s"),
			*Mesh->GetName(), *ErrorMessage.ToString());
		return nullptr;
	}

	FAssetRegistryModule::AssetCreated(PhysicsAsset);
	Package->MarkPackageDirty();

	UE_LOG(LogTemp, Display, TEXT("CreateBoxPhysicsAsset: created %s with %d bodies for %s"),
		*PackageName, PhysicsAsset->SkeletalBodySetups.Num(), *Mesh->GetName());

	return PhysicsAsset;
#else
	return nullptr;
#endif
}
