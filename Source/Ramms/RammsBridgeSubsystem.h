// RammsBridgeSubsystem.h
//
// Engine-level hub between the Remote Control receiver actor and the UI.
// One instance shared by the editor world, PIE and packaged games, so it does not
// matter which receiver copy a Remote Control call lands on.
//
//   Inbound  (bridge -> UE): receiver forwards raw JSON strings here -> delegates -> widgets parse
//   Outbound (UE -> bridge): widgets call PostButtonPress / PostObjectTapped -> UIEventsJson

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/EngineSubsystem.h"
#include "Dom/JsonObject.h"
#include "RammsBridgeSubsystem.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnRammsPanelJson, const FString&, PanelJson);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnRammsDetectedObjectsJson, const FString&, DetectedObjectsJson);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnRammsUIEventsJson, const FString&, UIEventsJson);

UCLASS()
class RAMMS_API URammsBridgeSubsystem : public UEngineSubsystem
{
	GENERATED_BODY()

public:
	virtual void Deinitialize() override;

	// ── Inbound (bridge -> UE) ────────────────────────────────────────

	/** Fired with the raw InteractionPanel JSON. Panel widget binds and parses. */
	UPROPERTY(BlueprintAssignable, Category = "Ramms Bridge|Inbound")
	FOnRammsPanelJson OnPanelJson;

	/** Fired with the raw {stream_id, selected_instance_id, objects} JSON. Overlay widget binds and parses. */
	UPROPERTY(BlueprintAssignable, Category = "Ramms Bridge|Inbound")
	FOnRammsDetectedObjectsJson OnDetectedObjectsJson;

	UFUNCTION(BlueprintCallable, Category = "Ramms Bridge|Inbound")
	void BroadcastPanelJson(const FString& PanelJson);

	UFUNCTION(BlueprintCallable, Category = "Ramms Bridge|Inbound")
	void BroadcastDetectedObjectsJson(const FString& DetectedObjectsJson);

	// ── Outbound (UE -> bridge) ───────────────────────────────────────

	/** Call from a panel button's OnClicked with that button's button_id. */
	UFUNCTION(BlueprintCallable, Category = "Ramms Bridge|Outbound")
	void PostButtonPress(const FString& ButtonId);

	/** Call from a detection box's OnClicked with that box's instance_id. */
	UFUNCTION(BlueprintCallable, Category = "Ramms Bridge|Outbound")
	void PostObjectTapped(const FString& InstanceId);

	/** Fired with the full {"latest_seq":N,"events":[...]} string after every event. Receiver binds. */
	UPROPERTY(BlueprintAssignable, Category = "Ramms Bridge|Outbound")
	FOnRammsUIEventsJson OnUIEventsJsonChanged;

	/** Current {"latest_seq":N,"events":[...]} string. */
	UFUNCTION(BlueprintPure, Category = "Ramms Bridge|Outbound")
	FString GetUIEventsJson() const { return CurrentUIEventsJson; }

	UFUNCTION(BlueprintPure, Category = "Ramms Bridge|Outbound")
	int32 GetLatestSequence() const { return Sequence; }

	/** For the polling fallback: every buffered event with seq > SinceSequence, as individual JSON strings. */
	void GetEventsSince(int32 SinceSequence, int32& OutLatestSequence, TArray<FString>& OutEvents) const;

	/** Raises a property-changed notification so Remote Control's WebSocket subscription sees code-side writes. */
	UFUNCTION(BlueprintCallable, Category = "Ramms Bridge|Outbound")
	static void NotifyPropertyChanged(UObject* Object, FName PropertyName);

private:
	void PushEvent(const TSharedRef<FJsonObject>& Event);

	struct FBufferedEvent
	{
		int32 Seq = 0;
		TSharedPtr<FJsonObject> Object;
		FString Json;
	};

	TArray<FBufferedEvent> RecentEvents;
	FString CurrentUIEventsJson = TEXT("{\"latest_seq\":0,\"events\":[]}");
	int32 Sequence = 0;

	static constexpr int32 MaxRecentEvents = 16;
};
