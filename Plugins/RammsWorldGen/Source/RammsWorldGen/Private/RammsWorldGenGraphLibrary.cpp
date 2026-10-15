// Copyright ATDev. All Rights Reserved.
#include "RammsWorldGenGraphLibrary.h"

#include "Elements/PCGSpawnActor.h"
#include "Elements/PCGStaticMeshSpawner.h"
#include "MeshSelectors/PCGMeshSelectorByAttribute.h"
#include "Metadata/PCGAttributePropertySelector.h"
#include "Engine/CollisionProfile.h"
#include "Metadata/PCGObjectPropertyOverride.h"
#include "PCG/RammsPCGCommon.h"
#include "RammsProcPiece.h"

TArray<FName> URammsWorldGenGraphLibrary::PiecePropertyNames()
{
	using namespace RammsPCG;
	return { KindId, SizeX, SizeY, SizeZ, Rise, Slope, FlareSlope, StepCount, OpeningWidth, OpeningOffset, OpeningHeight,
		LandingSize, WarningDepth, UVScale, MaterialPath, MaterialPath2, MaterialPath3, Openings, ManifestKind, ManifestSubtype, bCompliant, IssueId, Measure, Threshold };
}

void URammsWorldGenGraphLibrary::ConfigurePieceSpawner(UPCGSpawnActorSettings* Settings)
{
	if (!Settings)
	{
		return;
	}
	Settings->Modify();
	Settings->SetTemplateActorClass(ARammsProcPiece::StaticClass());
	Settings->Option = EPCGSpawnActorOption::NoMerging;
	Settings->AttachOptions = EPCGAttachOptions::Attached;
	Settings->PostSpawnFunctionNames = { FName(TEXT("Rebuild")) };
	Settings->TagsToAddOnActors = { FName(TEXT("RammsProcPiece")) };
	Settings->SpawnedActorPropertyOverrideDescriptions.Reset();
	for (const FName& Prop : PiecePropertyNames())
	{
		FPCGAttributePropertyInputSelector Selector;
		Selector.SetAttributeName(Prop);
		Settings->SpawnedActorPropertyOverrideDescriptions.Emplace(Selector, Prop.ToString());
	}
	Settings->MarkPackageDirty();
}

void URammsWorldGenGraphLibrary::ConfigureModuleSpawner(UPCGStaticMeshSpawnerSettings* Settings)
{
	if (!Settings)
	{
		return;
	}
	Settings->Modify();
	Settings->SetMeshSelectorType(UPCGMeshSelectorByAttribute::StaticClass());
	if (UPCGMeshSelectorByAttribute* Sel = Cast<UPCGMeshSelectorByAttribute>(Settings->MeshSelectorParameters))
	{
		Sel->AttributeName = RammsPCG::Mesh;
		// PCG's ISM template defaults to NoCollision: everything generated must be solid (players, the wheelchair
		// and the arm collide with it); meshes without simple collision get complex-as-simple at palette build.
		Sel->TemplateDescriptor.BodyInstance.SetCollisionProfileName(UCollisionProfile::BlockAll_ProfileName);
		Sel->bUseAttributeMaterialOverrides = true;
		Sel->MaterialOverrideAttributes.Reset();
		for (int32 i = 0; i < RammsPCG::NumModuleMaterials; ++i)
		{
			Sel->MaterialOverrideAttributes.Add(RammsPCG::ModuleMaterial(i));
		}
	}
	Settings->MarkPackageDirty();
}

void URammsWorldGenGraphLibrary::ConfigureFoliageSpawner(UPCGStaticMeshSpawnerSettings* Settings)
{
	if (!Settings)
	{
		return;
	}
	Settings->Modify();
	Settings->SetMeshSelectorType(UPCGMeshSelectorByAttribute::StaticClass());
	if (UPCGMeshSelectorByAttribute* Sel = Cast<UPCGMeshSelectorByAttribute>(Settings->MeshSelectorParameters))
	{
		Sel->AttributeName = RammsPCG::Mesh;
		Sel->TemplateDescriptor.BodyInstance.SetCollisionProfileName(UCollisionProfile::NoCollision_ProfileName);
		Sel->TemplateDescriptor.InstanceStartCullDistance = 4000;
		Sel->TemplateDescriptor.InstanceEndCullDistance = 7000;
		Sel->TemplateDescriptor.bAffectDistanceFieldLighting = false;
		Sel->TemplateDescriptor.bReceivesDecals = false;
		Sel->bUseAttributeMaterialOverrides = false;
		Sel->MaterialOverrideAttributes.Reset();
	}
	Settings->MarkPackageDirty();
}

void URammsWorldGenGraphLibrary::ConfigureMeshSpawner(UPCGStaticMeshSpawnerSettings* Settings, bool bMaterialFromAttribute)
{
	if (!Settings)
	{
		return;
	}
	Settings->Modify();
	Settings->SetMeshSelectorType(UPCGMeshSelectorByAttribute::StaticClass());
	if (UPCGMeshSelectorByAttribute* Sel = Cast<UPCGMeshSelectorByAttribute>(Settings->MeshSelectorParameters))
	{
		Sel->AttributeName = RammsPCG::Mesh;
		Sel->TemplateDescriptor.BodyInstance.SetCollisionProfileName(UCollisionProfile::BlockAll_ProfileName);
		Sel->bUseAttributeMaterialOverrides = bMaterialFromAttribute;
		Sel->MaterialOverrideAttributes.Reset();
		if (bMaterialFromAttribute)
		{
			Sel->MaterialOverrideAttributes.Add(RammsPCG::Material);
		}
	}
	Settings->MarkPackageDirty();
}
