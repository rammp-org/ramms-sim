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
#include "PCGGraph.h"
#include "PCGNode.h"
#include "PCGInputOutputSettings.h"
#include "UObject/UnrealType.h"
#if WITH_EDITOR
#include "Framework/Application/SlateApplication.h"
#include "Widgets/SWindow.h"
#include "SGraphPanel.h"
#include "EdGraph/EdGraph.h"
#include "ImageUtils.h"
#include "Misc/FileHelper.h"
#endif

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

namespace
{
	void ResetIOPins(UPCGNode* Node, const TArray<FName>& Labels)
	{
		UPCGGraphInputOutputSettings* IO = Node ? Cast<UPCGGraphInputOutputSettings>(Node->GetSettings()) : nullptr;
		if (!IO)
		{
			return;
		}
		IO->Modify();
		// Pins is protected; empty it through reflection, then add through the public API.
		if (FArrayProperty* Prop = FindFProperty<FArrayProperty>(UPCGGraphInputOutputSettings::StaticClass(), TEXT("Pins")))
		{
			FScriptArrayHelper Helper(Prop, Prop->ContainerPtrToValuePtr<void>(IO));
			Helper.EmptyValues();
		}
		for (const FName& Label : Labels)
		{
			(void)IO->AddPin(FPCGPinProperties(Label, FPCGDataTypeIdentifier{EPCGDataType::Any}));
		}
		Node->UpdateAfterSettingsChangeDuringCreation();
	}
}

void URammsWorldGenGraphLibrary::SetGraphPins(UPCGGraph* Graph, const TArray<FName>& InputPins, const TArray<FName>& OutputPins)
{
	if (!Graph)
	{
		return;
	}
	Graph->Modify();
	ResetIOPins(Graph->GetInputNode(), InputPins);
	ResetIOPins(Graph->GetOutputNode(), OutputPins);
	Graph->MarkPackageDirty();
}

void URammsWorldGenGraphLibrary::SetNodeComment(UPCGNode* Node, const FString& Comment)
{
#if WITH_EDITORONLY_DATA
	if (!Node)
	{
		return;
	}
	Node->Modify();
	Node->NodeComment = Comment;
	Node->bCommentBubblePinned = !Comment.IsEmpty();
	Node->bCommentBubbleVisible = !Comment.IsEmpty();
#endif
}

void URammsWorldGenGraphLibrary::ClearGraphComments(UPCGGraph* Graph)
{
#if WITH_EDITOR
	if (Graph)
	{
		Graph->Modify();
		Graph->SetCommentNodes({});
	}
#endif
}

void URammsWorldGenGraphLibrary::AddGraphComment(UPCGGraph* Graph, const FString& Text, int32 X, int32 Y, int32 Width, int32 Height, FLinearColor Color, int32 FontSize)
{
#if WITH_EDITOR
	if (!Graph)
	{
		return;
	}
	TArray<FPCGGraphCommentNodeData> Comments = Graph->GetCommentNodes();
	FPCGGraphCommentNodeData& C = Comments.AddDefaulted_GetRef();
	C.NodePosX = X;
	C.NodePosY = Y;
	C.NodeWidth = Width;
	C.NodeHeight = Height;
	C.NodeComment = Text;
	C.CommentColor = Color;
	C.FontSize = FontSize;
	// The box title is enough; no zoomed-out bubble repeating it.
	C.bColorCommentBubble = 0;
	C.bCommentBubbleVisible_InDetailsPanel = 0;
	C.bCommentBubbleVisible = 0;
	C.bCommentBubblePinned = 0;
	C.CommentDepth = -1;
	C.GUID = FGuid::NewGuid();
	Graph->Modify();
	Graph->SetCommentNodes(MoveTemp(Comments));
#endif
}

void URammsWorldGenGraphLibrary::RefreshNodePins(UPCGNode* Node)
{
	if (Node)
	{
		Node->UpdateAfterSettingsChangeDuringCreation();
	}
}

#if WITH_EDITOR
namespace
{
	TSharedPtr<SGraphPanel> FindPanel(const TSharedRef<SWidget>& Widget, const UPCGGraph* Graph)
	{
		const FString Type = Widget->GetTypeAsString();
		if (Type == TEXT("SGraphPanel"))
		{
			TSharedRef<SGraphPanel> Panel = StaticCastSharedRef<SGraphPanel>(Widget);
			const UEdGraph* Ed = Panel->GetGraphObj();
			if (Ed && Ed->GetTypedOuter<UPCGGraph>() == Graph)
			{
				return Panel;
			}
		}
		FChildren* Children = Widget->GetChildren();
		for (int32 i = 0; Children && i < Children->Num(); ++i)
		{
			if (TSharedPtr<SGraphPanel> Found = FindPanel(Children->GetChildAt(i), Graph))
			{
				return Found;
			}
		}
		return nullptr;
	}

	TSharedPtr<SGraphPanel> FindPanel(const UPCGGraph* Graph)
	{
		if (!Graph || !FSlateApplication::IsInitialized())
		{
			return nullptr;
		}
		// Asset editors usually float in their own window, a child of the main window.
		TArray<TSharedRef<SWindow>> Windows;
		FSlateApplication::Get().GetAllVisibleWindowsOrdered(Windows);
		for (const TSharedRef<SWindow>& Window : Windows)
		{
			if (TSharedPtr<SGraphPanel> Found = FindPanel(Window, Graph))
			{
				return Found;
			}
		}
		return nullptr;
	}
}
#endif

FIntPoint URammsWorldGenGraphLibrary::SetGraphEditorView(UPCGGraph* Graph, FVector2D TopLeft, float Zoom)
{
#if WITH_EDITOR
	if (TSharedPtr<SGraphPanel> Panel = FindPanel(Graph))
	{
		Panel->RestoreViewSettings(FVector2f(TopLeft), Zoom);
		const FVector2f Size = Panel->GetPaintSpaceGeometry().GetLocalSize();
		return FIntPoint(FMath::RoundToInt(Size.X), FMath::RoundToInt(Size.Y));
	}
#endif
	return FIntPoint::ZeroValue;
}

bool URammsWorldGenGraphLibrary::CaptureGraphEditor(UPCGGraph* Graph, const FString& PngPath)
{
#if WITH_EDITOR
	TSharedPtr<SGraphPanel> Panel = FindPanel(Graph);
	if (!Panel)
	{
		return false;
	}
	TArray<FColor> Pixels;
	FIntVector Size;
	if (!FSlateApplication::Get().TakeScreenshot(Panel.ToSharedRef(), Pixels, Size) || Size.X <= 0 || Size.Y <= 0)
	{
		return false;
	}
	for (FColor& C : Pixels)
	{
		C.A = 255;
	}
	TArray64<uint8> Png;
	FImageUtils::PNGCompressImageArray(Size.X, Size.Y, TArrayView64<const FColor>(Pixels.GetData(), Pixels.Num()), Png);
	return FFileHelper::SaveArrayToFile(Png, *PngPath);
#else
	return false;
#endif
}
