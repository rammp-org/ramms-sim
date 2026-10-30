// RammsBridgeReceiver.cpp

#include "RammsBridgeReceiver.h"
#include "RammsBridgeSubsystem.h"

#include "Engine/Engine.h"
#include "Engine/World.h"

ARammsBridgeReceiver::ARammsBridgeReceiver()
{
	PrimaryActorTick.bCanEverTick = false;
}

URammsBridgeSubsystem* ARammsBridgeReceiver::GetBridge()
{
	return GEngine ? GEngine->GetEngineSubsystem<URammsBridgeSubsystem>() : nullptr;
}

FString ARammsBridgeReceiver::GetWorldLabel() const
{
	// PIE worlds show a UEDPIE_N_ prefix, which makes it easy to see which copy was called
	const UWorld* World = GetWorld();
	return World ? World->GetMapName() : TEXT("<no world>");
}

// ── Inbound ───────────────────────────────────────────────────────

void ARammsBridgeReceiver::UpdatePanel(const FString& PanelJSON)
{
	UE_LOG(LogTemp, Log, TEXT("[Bridge] UpdatePanel (%s): %s"), *GetWorldLabel(), *PanelJSON);

	if (URammsBridgeSubsystem* Bridge = GetBridge())
	{
		Bridge->BroadcastPanelJson(PanelJSON);
	}
}

void ARammsBridgeReceiver::UpdateDetectedObjects(const FString& DetectedObjectsJSON)
{
	UE_LOG(LogTemp, Log, TEXT("[Bridge] UpdateDetectedObjects (%s): %s"), *GetWorldLabel(), *DetectedObjectsJSON);

	if (URammsBridgeSubsystem* Bridge = GetBridge())
	{
		Bridge->BroadcastDetectedObjectsJson(DetectedObjectsJSON);
	}
}

void ARammsBridgeReceiver::UpdateWorldState(const FString& WorldStateJSON)
{
	// Not in the current schema doc -- kept so the bridge doesn't error if it still calls it
	UE_LOG(LogTemp, Log, TEXT("[Bridge] UpdateWorldState (%s): %s"), *GetWorldLabel(), *WorldStateJSON);
}

// ── Outbound ──────────────────────────────────────────────────────

void ARammsBridgeReceiver::PollUIEvents(int32 SinceSequence, int32& LatestSequence, TArray<FString>& Events)
{
	LatestSequence = 0;
	Events.Reset();

	if (URammsBridgeSubsystem* Bridge = GetBridge())
	{
		Bridge->GetEventsSince(SinceSequence, LatestSequence, Events);
	}
}

void ARammsBridgeReceiver::BeginPlay()
{
	Super::BeginPlay();

	if (URammsBridgeSubsystem* Bridge = GetBridge())
	{
		UE_LOG(LogTemp, Log, TEXT("[Bridge] Receiver bound (%s)"), *GetWorldLabel());
		Bridge->OnUIEventsJsonChanged.AddUniqueDynamic(this, &ARammsBridgeReceiver::HandleUIEventsJsonChanged);
		UIEventsJson = Bridge->GetUIEventsJson();
	}
}

void ARammsBridgeReceiver::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (URammsBridgeSubsystem* Bridge = GetBridge())
	{
		Bridge->OnUIEventsJsonChanged.RemoveDynamic(this, &ARammsBridgeReceiver::HandleUIEventsJsonChanged);
	}

	Super::EndPlay(EndPlayReason);
}

void ARammsBridgeReceiver::HandleUIEventsJsonChanged(const FString& NewUIEventsJson)
{
	UE_LOG(LogTemp, Log, TEXT("[Bridge] Receiver got events (%s)"), *GetWorldLabel());
	UIEventsJson = NewUIEventsJson;

	// A plain assignment doesn't raise a change event; this is what the preset subscription listens for
	URammsBridgeSubsystem::NotifyPropertyChanged(this, GET_MEMBER_NAME_CHECKED(ARammsBridgeReceiver, UIEventsJson));
}
