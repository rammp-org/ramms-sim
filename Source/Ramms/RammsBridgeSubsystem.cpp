// RammsBridgeSubsystem.cpp

#include "RammsBridgeSubsystem.h"

#include "Dom/JsonValue.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"

namespace
{
	FString ToCondensedJson(const TSharedRef<FJsonObject>& Object)
	{
		FString Out;
		TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
			TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object, Writer);
		return Out;
	}
}

void URammsBridgeSubsystem::Deinitialize()
{
	OnPanelJson.Clear();
	OnDetectedObjectsJson.Clear();
	OnUIEventsJsonChanged.Clear();
	RecentEvents.Empty();
	Super::Deinitialize();
}

// ── Inbound ───────────────────────────────────────────────────────

void URammsBridgeSubsystem::BroadcastPanelJson(const FString& PanelJson)
{
	OnPanelJson.Broadcast(PanelJson);
}

void URammsBridgeSubsystem::BroadcastDetectedObjectsJson(const FString& DetectedObjectsJson)
{
	OnDetectedObjectsJson.Broadcast(DetectedObjectsJson);
}

// ── Outbound ──────────────────────────────────────────────────────

void URammsBridgeSubsystem::PostButtonPress(const FString& ButtonId)
{
	TSharedRef<FJsonObject> Event = MakeShared<FJsonObject>();
	Event->SetStringField(TEXT("event_type"), TEXT("button_press"));
	Event->SetStringField(TEXT("button_id"), ButtonId);
	PushEvent(Event);
}

void URammsBridgeSubsystem::PostObjectTapped(const FString& InstanceId)
{
	TSharedRef<FJsonObject> Event = MakeShared<FJsonObject>();
	Event->SetStringField(TEXT("event_type"), TEXT("object_tapped"));
	Event->SetStringField(TEXT("instance_id"), InstanceId);
	PushEvent(Event);
}

void URammsBridgeSubsystem::PushEvent(const TSharedRef<FJsonObject>& Event)
{
	Event->SetNumberField(TEXT("seq"), ++Sequence);

	FBufferedEvent& Buffered = RecentEvents.AddDefaulted_GetRef();
	Buffered.Seq    = Sequence;
	Buffered.Object = Event;
	Buffered.Json   = ToCondensedJson(Event);

	if (RecentEvents.Num() > MaxRecentEvents)
	{
		RecentEvents.RemoveAt(0);
	}

	TArray<TSharedPtr<FJsonValue>> EventValues;
	for (const FBufferedEvent& E : RecentEvents)
	{
		EventValues.Add(MakeShared<FJsonValueObject>(E.Object));
	}

	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetNumberField(TEXT("latest_seq"), Sequence);
	Root->SetArrayField(TEXT("events"), EventValues);

	CurrentUIEventsJson = ToCondensedJson(Root);

	UE_LOG(LogTemp, Log, TEXT("[Bridge] UI event: %s"), *CurrentUIEventsJson);
	OnUIEventsJsonChanged.Broadcast(CurrentUIEventsJson);
}

void URammsBridgeSubsystem::GetEventsSince(int32 SinceSequence, int32& OutLatestSequence, TArray<FString>& OutEvents) const
{
	OutLatestSequence = Sequence;
	for (const FBufferedEvent& E : RecentEvents)
	{
		if (E.Seq > SinceSequence)
		{
			OutEvents.Add(E.Json);
		}
	}
}

void URammsBridgeSubsystem::NotifyPropertyChanged(UObject* Object, FName PropertyName)
{
#if WITH_EDITOR
	if (!Object)
	{
		return;
	}

	if (FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName))
	{
		FPropertyChangedEvent ChangedEvent(Property, EPropertyChangeType::ValueSet);
		FCoreUObjectDelegates::OnObjectPropertyChanged.Broadcast(Object, ChangedEvent);
	}
	else
	{
		UE_LOG(LogTemp, Warning, TEXT("[Bridge] NotifyPropertyChanged: '%s' has no property '%s'"),
			*Object->GetName(), *PropertyName.ToString());
	}
#endif
}
