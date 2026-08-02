#include "CabinetPhysicsTools.h"

#include "Engine/SkeletalMesh.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/SkeletalBodySetup.h"
#include "PhysicsEngine/PhysicsConstraintTemplate.h"

#if WITH_EDITOR
	#include "Rendering/SkeletalMeshModel.h"
	#include "Rendering/SkeletalMeshLODModel.h"
	#include "AssetRegistry/AssetRegistryModule.h"
	#include "UObject/Package.h"
#endif

UPhysicsAsset* UCabinetPhysicsTools::CreateBoxPhysicsAsset(USkeletalMesh* Mesh,
	const FString&														  PackagePath,
	const FString&														  AssetName,
	float																  MinSize,
	bool																  bBodyForAll,
	bool																  bCreateConstraints)
{
#if !WITH_EDITOR
	return nullptr;
#else
	if (!Mesh || !Mesh->GetImportedModel() || Mesh->GetImportedModel()->LODModels.Num() == 0)
	{
		UE_LOG(LogTemp, Warning, TEXT("CreateBoxPhysicsAsset: no mesh / editor LOD data"));
		return nullptr;
	}

	const FReferenceSkeleton& RefSkel = Mesh->GetRefSkeleton();
	const int32				  NumBones = RefSkel.GetNum();

	// component-space reference pose
	TArray<FTransform> CompPose;
	CompPose.SetNum(NumBones);
	for (int32 i = 0; i < NumBones; ++i)
	{
		const int32 Parent = RefSkel.GetParentIndex(i);
		CompPose[i] = (Parent == INDEX_NONE)
			? RefSkel.GetRefBonePose()[i]
			: RefSkel.GetRefBonePose()[i] * CompPose[Parent];
	}

	// per-bone AABB of dominantly-skinned vertices, in bone space
	TArray<FBox> BoneBounds;
	BoneBounds.Init(FBox(ForceInit), NumBones);
	const FSkeletalMeshLODModel& LOD = Mesh->GetImportedModel()->LODModels[0];
	for (const FSkelMeshSection& Section : LOD.Sections)
	{
		for (const FSoftSkinVertex& V : Section.SoftVertices)
		{
			int32 Best = 0;
			for (int32 k = 1; k < MAX_TOTAL_INFLUENCES; ++k)
			{
				if (V.InfluenceWeights[k] > V.InfluenceWeights[Best])
				{
					Best = k;
				}
			}
			if (V.InfluenceWeights[Best] == 0)
			{
				continue;
			}
			const int32	  BoneIndex = Section.BoneMap[V.InfluenceBones[Best]];
			const FVector BonePos =
				CompPose[BoneIndex].InverseTransformPosition(FVector(V.Position));
			BoneBounds[BoneIndex] += BonePos;
		}
	}

	// the asset
	const FString  PackageName = PackagePath / AssetName;
	UPackage*	   Package = CreatePackage(*PackageName);
	UPhysicsAsset* PhysAsset = NewObject<UPhysicsAsset>(
		Package, FName(*AssetName), RF_Public | RF_Standalone);

	TArray<int32> BodyIndexOfBone;
	BodyIndexOfBone.Init(INDEX_NONE, NumBones);
	for (int32 i = 0; i < NumBones; ++i)
	{
		if (!BoneBounds[i].IsValid)
		{
			continue; // bone with no skinned vertices
		}
		const FVector Size = BoneBounds[i].GetSize();
		if (!bBodyForAll && Size.GetMax() < MinSize)
		{
			continue;
		}
		USkeletalBodySetup* Body = NewObject<USkeletalBodySetup>(PhysAsset, NAME_None);
		Body->BoneName = RefSkel.GetBoneName(i);
		Body->PhysicsType = PhysType_Default;
		Body->CollisionTraceFlag = CTF_UseSimpleAsComplex;
		FKBoxElem Box;
		Box.Center = BoneBounds[i].GetCenter();
		Box.X = FMath::Max(Size.X, MinSize);
		Box.Y = FMath::Max(Size.Y, MinSize);
		Box.Z = FMath::Max(Size.Z, MinSize);
		Body->AggGeom.BoxElems.Add(Box);
		BodyIndexOfBone[i] = PhysAsset->SkeletalBodySetups.Add(Body);
	}

	if (bCreateConstraints)
	{
		for (int32 i = 0; i < NumBones; ++i)
		{
			if (BodyIndexOfBone[i] == INDEX_NONE)
			{
				continue;
			}
			int32 Parent = RefSkel.GetParentIndex(i);
			while (Parent != INDEX_NONE && BodyIndexOfBone[Parent] == INDEX_NONE)
			{
				Parent = RefSkel.GetParentIndex(Parent);
			}
			if (Parent == INDEX_NONE)
			{
				continue; // root body: no constraint
			}
			UPhysicsConstraintTemplate* Tpl =
				NewObject<UPhysicsConstraintTemplate>(PhysAsset, NAME_None);
			FConstraintInstance& CI = Tpl->DefaultInstance;
			CI.JointName = RefSkel.GetBoneName(i);
			CI.ConstraintBone1 = RefSkel.GetBoneName(i);	  // child
			CI.ConstraintBone2 = RefSkel.GetBoneName(Parent); // parent
			// joint at the child bone origin, fully locked by default --
			// the door/drawer axes get opened per the export manifest
			CI.SetRefFrame(EConstraintFrame::Frame1, FTransform::Identity);
			CI.SetRefFrame(EConstraintFrame::Frame2,
				CompPose[i].GetRelativeTransform(CompPose[Parent]));
			CI.SetLinearXLimit(LCM_Locked, 0.f);
			CI.SetLinearYLimit(LCM_Locked, 0.f);
			CI.SetLinearZLimit(LCM_Locked, 0.f);
			CI.SetAngularSwing1Limit(ACM_Locked, 0.f);
			CI.SetAngularSwing2Limit(ACM_Locked, 0.f);
			CI.SetAngularTwistLimit(ACM_Locked, 0.f);
			CI.SetDisableCollision(true);
			PhysAsset->ConstraintSetup.Add(Tpl);
		}
	}

	PhysAsset->UpdateBodySetupIndexMap();
	PhysAsset->UpdateBoundsBodiesArray();
	PhysAsset->SetPreviewMesh(Mesh);
	Mesh->SetPhysicsAsset(PhysAsset);

	FAssetRegistryModule::AssetCreated(PhysAsset);
	PhysAsset->MarkPackageDirty();
	Mesh->MarkPackageDirty();
	return PhysAsset;
#endif
}
