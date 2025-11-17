import streamlit as st
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@st.cache_data
def load_data():
    df = pd.read_csv("Cleaned_Medicine_List_with_Alternatives.csv")
    df.drop_duplicates(subset=['Medicine Name', 'Composition'], inplace=True)
    df.dropna(subset=['Composition'], inplace=True)
    df['Drug Class'] = df['Drug Class'].fillna("Unknown")
    return df

df = load_data()


vectorizer = TfidfVectorizer()
tfidf_matrix = vectorizer.fit_transform(df['Composition'])


def suggest_best_alternate(med_name, df, tfidf_matrix, similarity_threshold=0.7):
    idx = df[df['Medicine Name'].str.lower() == med_name.lower()].index
    if len(idx) == 0:
        return f"❌ Medicine '{med_name}' not found in the dataset!"

    idx = idx[0]
    cosine_sim = cosine_similarity(tfidf_matrix[idx], tfidf_matrix).flatten()
    cosine_sim[idx] = 0  # exclude itself
    best_match_idx = cosine_sim.argmax()
    best_score = cosine_sim[best_match_idx]

    if best_score < similarity_threshold:
        return f"⚠️ No highly similar alternative found for '{med_name}' (Max similarity = {best_score:.2f})"

    result = df.iloc[[best_match_idx]][['Medicine Name', 'Composition', 'Use Case', 'Type', 'Drug Class']]
    result.insert(0, "📈 Similarity", f"{best_score*100:.2f}%")
    return result

# Streamlit UI Theme
page_bg = '''
<style>
[data-testid="stAppViewContainer"] > .main {
    background-image: linear-gradient(to right, #eef2f3, #8e9eab);
    background-size: cover;
}
[data-testid="stHeader"] {
    background-color: rgba(0,0,0,0);
}
[data-testid="stSidebar"] {
    background-color: #f7f7f7;
}
</style>
'''
st.markdown(page_bg, unsafe_allow_html=True)

# UI Components
st.title("💊 Alternate Medicine Suggestion System (Best Match Only)")
st.markdown("""
Get the **most similar alternate medicine** based on composition with at least **70% similarity**. 
Safe, accurate, and pharmacist-style suggestions 🔍
""")

medicine_name = st.text_input("🔍 Enter a Medicine Name:")

if st.button("💡 Find Best Match"):
    if medicine_name:
        result = suggest_best_alternate(medicine_name, df, tfidf_matrix)
        if isinstance(result, pd.DataFrame):
            st.success(f"✅ Best alternate for '{medicine_name}':")
            st.dataframe(result, use_container_width=True)
        else:
            st.warning(result)
    else:
        st.info("✍️ Please enter a medicine name to search.")
