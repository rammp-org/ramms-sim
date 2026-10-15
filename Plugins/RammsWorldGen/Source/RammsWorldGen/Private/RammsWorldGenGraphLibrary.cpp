// Copyright ATDev. All Rights Reserved.
#include "RammsWorldGenGraphLibrary.h"

#include "Elements/PCGSpawnActor.h"
#include "Elements/PCGStaticMeshSpawner.h"
#include "MeshSelectors/PCGMeshSelectorByAttribute.h"
#include "Metadata/PCGAttributePropertySelector.h"
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
		Sel->bUseAttributeMaterialOverrides = true;
		Sel->MaterialOverrideAttributes.Reset();
		for (int32 i = 0; i < RammsPCG::NumModuleMaterials; ++i)
		{
			Sel->MaterialOverrideAttributes.Add(RammsPCG::ModuleMaterial(i));
		}
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
		Sel->bUseAttributeMaterialOverrides = bMaterialFromAttribute;
		Sel->MaterialOverrideAttributes.Reset();
		if (bMaterialFromAttribute)
		{
			Sel->MaterialOverrideAttributes.Add(RammsPCG::Material);
		}
	}
	Settings->MarkPackageDirty();
}
